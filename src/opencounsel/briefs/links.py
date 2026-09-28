from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from opencounsel.briefs.ir import BriefAudit

DEFAULT_ALLOWED_HOSTS = (
    "courtlistener.com",
    "www.courtlistener.com",
    "uscode.house.gov",
    "www.ecfr.gov",
    "www.nycourts.gov",
    "www.nysenate.gov",
    "www.law.cornell.edu",
)


@dataclass(frozen=True, slots=True)
class AuthorityResolution:
    normalized_citation: str
    status: str
    url: str | None
    resolver: str
    source_type: str = "unknown"


@dataclass(frozen=True, slots=True)
class LinkInsertion:
    part: str
    paragraph_index: int
    start: int
    end: int
    expected_text: str
    url: str
    resolver: str
    source_type: str = "unknown"


@dataclass(frozen=True, slots=True)
class LinkReviewItem:
    part: str
    paragraph_index: int
    citation: str
    reason: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True, slots=True)
class AuthorityLinkPlan:
    brief_sha256: str
    insertions: tuple[LinkInsertion, ...]
    review: tuple[LinkReviewItem, ...]


def plan_authority_links(
    audit: BriefAudit,
    resolutions: tuple[AuthorityResolution, ...],
    *,
    allowed_hosts: tuple[str, ...] = DEFAULT_ALLOWED_HOSTS,
) -> AuthorityLinkPlan:
    by_citation: dict[str, list[AuthorityResolution]] = {}
    for resolution in resolutions:
        by_citation.setdefault(resolution.normalized_citation.casefold(), []).append(resolution)

    insertions: list[LinkInsertion] = []
    review: list[LinkReviewItem] = []
    for authority in audit.authorities:
        if authority.hyperlink_target:
            continue
        citation_key = authority.resolved_citation or authority.normalized_text
        if not authority.is_link_candidate:
            if authority.citation_type in {"IdCitation", "ShortCaseCitation", "SupraCitation"}:
                review.append(
                    LinkReviewItem(
                        authority.part,
                        authority.paragraph_index,
                        authority.normalized_text,
                        "short-form citation has no uniquely approved antecedent",
                        authority.start,
                        authority.end,
                    )
                )
            continue
        matches = by_citation.get(citation_key.casefold(), [])
        verified = [resolution for resolution in matches if resolution.status == "verified"]
        if len(verified) != 1:
            reason = "no verified resolution" if not verified else "multiple verified resolutions"
            review.append(
                LinkReviewItem(
                    authority.part,
                    authority.paragraph_index,
                    authority.normalized_text,
                    reason,
                    authority.start,
                    authority.end,
                )
            )
            continue
        resolution = verified[0]
        if resolution.url is None or not _allowed_resolution(resolution, allowed_hosts):
            review.append(
                LinkReviewItem(
                    authority.part,
                    authority.paragraph_index,
                    authority.normalized_text,
                    "resolver URL is not on the allowlist",
                    authority.start,
                    authority.end,
                )
            )
            continue
        insertions.append(
            LinkInsertion(
                authority.part,
                authority.paragraph_index,
                authority.start,
                authority.end,
                authority.text,
                resolution.url,
                resolution.resolver,
                resolution.source_type,
            )
        )
    return AuthorityLinkPlan(audit.brief_sha256, tuple(insertions), tuple(review))


def _allowed_url(url: str, allowed_hosts: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme == "https"
        and parsed.hostname in allowed_hosts
        and not parsed.username
        and not parsed.password
    )


def _allowed_resolution(
    resolution: AuthorityResolution, allowed_hosts: tuple[str, ...]
) -> bool:
    if resolution.url is None:
        return False
    if resolution.resolver == "local-source-override":
        parsed = urlparse(resolution.url)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    return _allowed_url(resolution.url, allowed_hosts)
