from __future__ import annotations

import json
import os
import tomllib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from opencounsel.briefs.ir import AuthorityOccurrence, BriefAudit
from opencounsel.briefs.links import AuthorityResolution

COURTLISTENER_LOOKUP_URL = "https://www.courtlistener.com/api/rest/v4/citation-lookup/"
COURTLISTENER_SEARCH_URL = "https://www.courtlistener.com/api/rest/v4/search/"
COURTLISTENER_BASE_URL = "https://www.courtlistener.com"
DEFAULT_TOKEN_ENV = "COURTLISTENER_API_TOKEN"


class ReadableResponse(Protocol):
    def read(self, amount: int = -1) -> bytes: ...


type UrlOpener = Callable[..., ReadableResponse]


class SourceResolutionError(ValueError):
    """Raised when a source manifest or bounded resolver response is invalid."""


@dataclass(frozen=True, slots=True)
class SourceOverride:
    citation: str
    url: str
    note: str | None = None


def resolve_authority_sources(
    audit: BriefAudit,
    *,
    overrides: tuple[SourceOverride, ...] = (),
    use_courtlistener: bool = False,
    courtlistener_token: str | None = None,
    opener: UrlOpener = urlopen,
) -> tuple[AuthorityResolution, ...]:
    """Resolve canonical citations without transmitting document prose or context."""
    by_citation = {item.citation.casefold(): item for item in overrides}
    results: list[AuthorityResolution] = []
    unresolved_cases: list[str] = []
    seen: set[str] = set()

    for authority in audit.authorities:
        key = authority.normalized_text.casefold()
        if not authority.is_canonical_candidate or authority.hyperlink_target or key in seen:
            continue
        seen.add(key)
        override = _matching_override(authority, by_citation)
        if override is not None:
            results.append(
                AuthorityResolution(
                    authority.normalized_text,
                    "verified",
                    override.url,
                    "local-source-override",
                    source_type="licensed-or-manual",
                )
            )
            continue
        official = official_source_for(authority)
        if official is not None:
            results.append(official)
            continue
        if authority.category == "cases":
            unresolved_cases.append(authority.normalized_text)

    if use_courtlistener and unresolved_cases:
        token = courtlistener_token or os.environ.get(DEFAULT_TOKEN_ENV)
        if not token:
            raise SourceResolutionError(
                f"CourtListener requested but {DEFAULT_TOKEN_ENV} is not set"
            )
        looked_up = _courtlistener_lookup(tuple(unresolved_cases), token, opener=opener)
        results.extend(looked_up)
        resolved_keys = {item.normalized_citation.casefold() for item in looked_up}
        search_candidates: dict[str, AuthorityOccurrence] = {}
        for authority in audit.authorities:
            key = authority.normalized_text.casefold()
            if (
                authority.is_canonical_candidate
                and authority.category == "cases"
                and authority.citation_type == "VendorCaseCitation"
                and authority.case_name
                and key not in resolved_keys
                and authority.normalized_text in unresolved_cases
            ):
                search_candidates.setdefault(key, authority)
        for authority in search_candidates.values():
            resolution = _courtlistener_search(authority, token, opener=opener)
            if resolution is not None:
                results.append(resolution)
    return tuple(results)


def _matching_override(
    authority: AuthorityOccurrence,
    by_citation: dict[str, SourceOverride],
) -> SourceOverride | None:
    for citation in (authority.normalized_text, authority.toa_display):
        if citation is not None and (override := by_citation.get(citation.casefold())):
            return override
    return None


def official_source_for(authority: AuthorityOccurrence) -> AuthorityResolution | None:
    groups = dict(authority.groups)
    if groups.get("jurisdiction") == "federal" and (ruleset := groups.get("ruleset")):
        rule = groups.get("rule")
        if rule:
            rule_number = _base_section(rule)
            return AuthorityResolution(
                authority.normalized_text,
                "verified",
                f"https://www.law.cornell.edu/rules/{quote(ruleset)}/rule_{quote(rule_number)}",
                "cornell-lii-federal-rules-url",
                source_type="open-secondary",
            )
    if groups.get("reporter") == "NY Slip Op":
        year = groups.get("volume")
        opinion_number = groups.get("page")
        if year and opinion_number:
            url = (
                "https://www.nycourts.gov/reporter/3dseries/"
                f"{quote(year)}/{quote(year)}_{quote(opinion_number)}.htm"
            )
            return AuthorityResolution(
                authority.normalized_text,
                "verified",
                url,
                "ny-law-reporting-bureau-slip-url",
                source_type="official",
            )
    section = groups.get("section")
    if not section:
        return None
    reporter = groups.get("reporter")
    if reporter == "U.S.C.":
        title = groups.get("title")
        if not title:
            return None
        base_section = _base_section(section)
        url = (
            "https://uscode.house.gov/view.xhtml?req="
            f"granuleid:USC-prelim-title{quote(title)}-section{quote(base_section)}"
            "&num=0&edition=prelim"
        )
        return AuthorityResolution(
            authority.normalized_text,
            "verified",
            url,
            "us-house-olrc-url",
            source_type="official",
        )
    if reporter == "C.F.R.":
        title = groups.get("title")
        if not title:
            return None
        url = (
            f"https://www.ecfr.gov/current/title-{quote(title)}"
            f"/section-{quote(_base_section(section))}"
        )
        return AuthorityResolution(
            authority.normalized_text,
            "verified",
            url,
            "ecfr-current-url",
            source_type="official",
        )
    if groups.get("jurisdiction") == "ny" and (code := groups.get("code")):
        url = (
            "https://www.nysenate.gov/legislation/laws/"
            f"{quote(code.upper())}/{quote(_base_section(section))}"
        )
        return AuthorityResolution(
            authority.normalized_text,
            "verified",
            url,
            "ny-senate-open-legislation-url",
            source_type="official",
        )
    return None


def load_source_overrides(path: Path) -> tuple[SourceOverride, ...]:
    if not path.is_file() or path.is_symlink():
        raise SourceResolutionError("source override manifest must be a regular TOML file")
    if path.stat().st_size > 1024 * 1024:
        raise SourceResolutionError("source override manifest exceeds 1 MiB")
    try:
        with path.open("rb") as stream:
            values = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SourceResolutionError("source override manifest is not valid TOML") from exc
    if values.get("schema_version") != 1:
        raise SourceResolutionError("unsupported source override schema")
    raw_items = values.get("authority", [])
    if not isinstance(raw_items, list):
        raise SourceResolutionError("source override authority entries must be an array")
    overrides: list[SourceOverride] = []
    seen: set[str] = set()
    for item in raw_items:
        if not isinstance(item, dict):
            raise SourceResolutionError("source override entry must be a table")
        citation = item.get("citation")
        url = item.get("url")
        note = item.get("note")
        if not isinstance(citation, str) or not citation.strip():
            raise SourceResolutionError("source override citation must be non-empty text")
        if not isinstance(url, str) or not _stable_authority_url(url):
            raise SourceResolutionError(
                "source override URL must be a stable credential-free HTTPS authority target"
            )
        if note is not None and not isinstance(note, str):
            raise SourceResolutionError("source override note must be text")
        key = citation.casefold()
        if key in seen:
            raise SourceResolutionError("source override citations must be unique")
        seen.add(key)
        overrides.append(SourceOverride(citation, url, note))
    return tuple(overrides)


def _courtlistener_lookup(
    citations: tuple[str, ...],
    token: str,
    *,
    opener: UrlOpener,
) -> tuple[AuthorityResolution, ...]:
    # Newline separation sends only reporter strings while preserving API result offsets.
    payload = "\n".join(citations)
    request = Request(
        COURTLISTENER_LOOKUP_URL,
        data=urlencode({"text": payload}).encode("utf-8"),
        headers={
            "Authorization": f"Token {token}",
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "OpenCounsel/0.1 citation-resolver",
        },
        method="POST",
    )
    try:
        response = opener(request, timeout=20)
        body = response.read(1024 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SourceResolutionError("CourtListener citation lookup failed") from exc
    if len(body) > 1024 * 1024:
        raise SourceResolutionError("CourtListener response exceeded 1 MiB")
    try:
        values = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceResolutionError("CourtListener returned invalid JSON") from exc
    if not isinstance(values, list):
        raise SourceResolutionError("CourtListener returned an invalid result shape")

    resolutions: list[AuthorityResolution] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        citation = item.get("citation")
        clusters = item.get("clusters")
        status = item.get("status")
        if not isinstance(citation, str) or status != 200 or not isinstance(clusters, list):
            continue
        urls: set[str] = set()
        for cluster in clusters:
            if not isinstance(cluster, dict):
                continue
            absolute_url = cluster.get("absolute_url")
            if isinstance(absolute_url, str) and (
                resolved_url := _courtlistener_url(absolute_url)
            ):
                urls.add(resolved_url)
        if len(urls) != 1:
            continue
        resolutions.append(
            AuthorityResolution(
                citation,
                "verified",
                urls.pop(),
                "courtlistener-citation-lookup-v4",
                source_type="open-opinion-repository",
            )
        )
    return tuple(resolutions)


def _courtlistener_url(value: str) -> str | None:
    url = urljoin(COURTLISTENER_BASE_URL, value)
    hostname = (urlparse(url).hostname or "").casefold()
    allowed = {"courtlistener.com", "www.courtlistener.com"}
    return url if hostname in allowed and _stable_authority_url(url) else None


def _courtlistener_search(
    authority: AuthorityOccurrence,
    token: str,
    *,
    opener: UrlOpener,
) -> AuthorityResolution | None:
    groups = dict(authority.groups)
    query = " ".join(
        value
        for value in (authority.case_name, groups.get("year"), authority.normalized_text)
        if value
    )
    url = f"{COURTLISTENER_SEARCH_URL}?{urlencode({'type': 'o', 'q': query})}"
    request = Request(
        url,
        headers={
            "Authorization": f"Token {token}",
            "User-Agent": "OpenCounsel/0.1 authority-search",
        },
        method="GET",
    )
    values = _read_courtlistener_json(request, opener)
    if not isinstance(values, dict) or not isinstance(values.get("results"), list):
        raise SourceResolutionError("CourtListener search returned an invalid result shape")
    expected_name = _name_key(authority.case_name)
    expected_year = groups.get("year")
    urls: set[str] = set()
    for item in values["results"]:
        if not isinstance(item, dict):
            continue
        result_name = item.get("caseName") or item.get("case_name")
        result_url = item.get("absolute_url")
        date_filed = item.get("dateFiled") or item.get("date_filed")
        if not isinstance(result_name, str) or not isinstance(result_url, str):
            continue
        actual_name = _name_key(result_name)
        if expected_name not in actual_name and actual_name not in expected_name:
            continue
        if (
            expected_year
            and isinstance(date_filed, str)
            and not date_filed.startswith(expected_year)
        ):
            continue
        if safe_url := _courtlistener_url(result_url):
            urls.add(safe_url)
    if len(urls) != 1:
        return None
    return AuthorityResolution(
        authority.normalized_text,
        "verified",
        urls.pop(),
        "courtlistener-search-v4",
        source_type="open-opinion-repository",
    )


def _read_courtlistener_json(
    request: Request,
    opener: UrlOpener,
) -> object:
    try:
        response = opener(request, timeout=20)
        body = response.read(1024 * 1024 + 1)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise SourceResolutionError("CourtListener search failed") from exc
    if len(body) > 1024 * 1024:
        raise SourceResolutionError("CourtListener search response exceeded 1 MiB")
    try:
        return json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceResolutionError("CourtListener search returned invalid JSON") from exc


def _name_key(value: str | None) -> str:
    return "".join(character for character in (value or "").casefold() if character.isalnum())


def _stable_authority_url(url: str) -> bool:
    if not _safe_https_url(url):
        return False
    parsed = urlparse(url)
    if (parsed.hostname or "").casefold() not in {
        "courtlistener.com",
        "www.courtlistener.com",
    }:
        return True
    segments = tuple(segment.casefold() for segment in parsed.path.split("/") if segment)
    return (
        len(segments) >= 2
        and segments[0] == "opinion"
        and segments[1].isdigit()
        and not parsed.query
        and not parsed.fragment
    )


def _safe_https_url(url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and bool(parsed.hostname)
        and not parsed.username
        and not parsed.password
    )


def _base_section(section: str) -> str:
    return section.split("(", maxsplit=1)[0]
