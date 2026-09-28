from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from opencounsel.source.authority_package import AuthorityPackageError

_QUOTE_RE = re.compile(r"[\"“](?P<quote>[^\"”]{4,})[\"”]")
_SIGNAL_RE = re.compile(
    r"\b(?:citation(?:s)? omitted|cleaned up|alteration(?:s)? in original|"
    r"emphasis (?:added|omitted)|internal quotation marks omitted)\b",
    re.IGNORECASE,
)
_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9']{2,}")


def verify_authority_package(package: Path, output: Path) -> dict[str, object]:
    if not package.is_file() or package.is_symlink() or package.suffix.lower() != ".zip":
        raise AuthorityPackageError("authority package must be a regular ZIP file")
    if output.exists():
        raise AuthorityPackageError("authority verification report already exists")
    try:
        archive = zipfile.ZipFile(package)
    except (OSError, zipfile.BadZipFile) as exc:
        raise AuthorityPackageError("authority package is not a readable ZIP") from exc
    with archive:
        names = _safe_members(archive)
        required = {"manifest.json", "pages.jsonl", "brief-authority-manifest.json"}
        if not required.issubset(names):
            raise AuthorityPackageError("authority package is missing required metadata")
        package_manifest = _json_object(archive.read("manifest.json"), "package manifest")
        brief_manifest = _json_object(
            archive.read("brief-authority-manifest.json"), "brief authority manifest"
        )
        pages = _json_lines(archive.read("pages.jsonl"))

    manifest_sources = package_manifest.get("sources")
    if not isinstance(manifest_sources, list):
        raise AuthorityPackageError("package manifest has an unsupported source ledger")
    source_ids = {
        item.get("authority_id")
        for item in manifest_sources
        if isinstance(item, dict)
    }
    pages_by_authority: dict[str, list[dict[str, object]]] = {}
    for page in pages:
        authority_id = page.get("authority_id")
        if isinstance(authority_id, str):
            pages_by_authority.setdefault(authority_id, []).append(page)

    manifest_authorities = brief_manifest.get("authorities")
    if not isinstance(manifest_authorities, list):
        raise AuthorityPackageError("brief authority manifest has an unsupported authority ledger")
    results: list[dict[str, object]] = []
    source_present_count = 0
    citation_confirmed_count = 0
    assertion_count = 0
    quotation_failure_count = 0
    characterization_review_count = 0
    for authority in manifest_authorities:
        if not isinstance(authority, dict) or not isinstance(authority.get("authority_id"), str):
            continue
        authority_id = authority["authority_id"]
        authority_pages = pages_by_authority.get(authority_id, [])
        exists = authority_id in source_ids and bool(authority_pages)
        source_text = _normalize_text(
            "\n".join(str(page.get("text", "")) for page in authority_pages)
        )
        citation_key = _normalize_text(str(authority.get("canonical_citation", "")))
        case_name_key = _normalize_text(str(authority.get("case_name", "")))
        identity_match = exists and bool(
            (citation_key and citation_key in source_text)
            or (case_name_key and case_name_key in source_text)
        )
        assertions = authority.get("assertions")
        if not isinstance(assertions, list):
            assertions = []
        assertion_results = [
            _verify_assertion(assertion, authority_pages, source_text, exists)
            for assertion in assertions
            if isinstance(assertion, dict)
        ]
        source_present_count += int(exists)
        citation_confirmed_count += int(identity_match)
        assertion_count += len(assertion_results)
        quotation_failure_count += sum(
            result["quotation_exact"] == "fail" for result in assertion_results
        )
        characterization_review_count += sum(
            result["characterization_supported"] == "review-required"
            for result in assertion_results
        )
        results.append(
            {
                "authority_id": authority_id,
                "canonical_citation": authority.get("canonical_citation"),
                "source_present": "pass" if exists else "fail",
                "citation_exists": (
                    "pass" if identity_match else "review-required" if exists else "fail"
                ),
                "assertions": assertion_results,
            }
        )

    summary: dict[str, object] = {
        "authority_count": len(results),
        "source_present_count": source_present_count,
        "citation_confirmed_count": citation_confirmed_count,
        "assertion_count": assertion_count,
        "quotation_failure_count": quotation_failure_count,
        "characterization_review_count": characterization_review_count,
    }
    payload = {
        "schema_version": 1,
        "package_sha256": _hash_path(package),
        "summary": summary,
        "authorities": results,
    }
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return summary


def _verify_assertion(
    assertion: dict[str, object],
    pages: list[dict[str, object]],
    source_text: str,
    exists: bool,
) -> dict[str, object]:
    context = str(assertion.get("context", ""))
    quotes = [" ".join(match.group("quote").split()) for match in _QUOTE_RE.finditer(context)]
    exact_results = [
        {"text": quote, "exact_match": _normalize_text(quote) in source_text}
        for quote in quotes
    ]
    if not exists:
        quotation_status = "blocked-no-source"
        signal_status = "blocked-no-source"
        characterization = "blocked-no-source"
    elif not quotes:
        quotation_status = "not-applicable"
        signal_status = "not-applicable"
        characterization = "review-required"
    else:
        quotation_status = "pass" if all(item["exact_match"] for item in exact_results) else "fail"
        transformed = any("..." in quote or "…" in quote or "[" in quote for quote in quotes)
        signal_status = "review-required" if transformed else quotation_status
        characterization = "review-required"
    return {
        "part": assertion.get("part"),
        "paragraph_index": assertion.get("paragraph_index"),
        "citation_text": assertion.get("citation_text"),
        "assertion_context": context,
        "quotation_exact": quotation_status,
        "quotation_checks": exact_results,
        "quotation_signals_complete": signal_status,
        "signals_found": sorted(set(match.group(0) for match in _SIGNAL_RE.finditer(context))),
        "characterization_supported": characterization,
        "likely_pertinent_pages": _rank_pages(context, pages) if exists else [],
    }


def _rank_pages(context: str, pages: list[dict[str, object]]) -> list[int]:
    query = {token.casefold() for token in _TOKEN_RE.findall(context) if len(token) > 3}
    ranked: list[tuple[int, int]] = []
    for page in pages:
        page_number = page.get("page_number")
        if not isinstance(page_number, int):
            continue
        tokens = {token.casefold() for token in _TOKEN_RE.findall(str(page.get("text", "")))}
        ranked.append((len(query & tokens), page_number))
    ordered = sorted(ranked, key=lambda item: (-item[0], item[1]))[:3]
    return [page for score, page in ordered if score]


def _safe_members(archive: zipfile.ZipFile) -> set[str]:
    names: set[str] = set()
    total = 0
    for member in archive.infolist():
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or not path.name or member.filename in names:
            raise AuthorityPackageError("authority package contains an unsafe member path")
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode) or member.flag_bits & 0x1:
            raise AuthorityPackageError("authority package contains an unsafe member")
        total += member.file_size
        if member.file_size > 100 * 1024 * 1024 or total > 500 * 1024 * 1024:
            raise AuthorityPackageError("authority package exceeds size limits")
        names.add(member.filename)
    if archive.testzip() is not None:
        raise AuthorityPackageError("authority package failed its CRC check")
    return names


def _json_object(data: bytes, label: str) -> dict[str, object]:
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityPackageError(f"{label} is invalid JSON") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise AuthorityPackageError(f"{label} has an unsupported schema")
    return value


def _json_lines(data: bytes) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    try:
        for line in data.decode().splitlines():
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError
            rows.append(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise AuthorityPackageError("authority page ledger is invalid JSONL") from exc
    return rows


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).replace("\u00ad", "")
    return " ".join(value.split()).casefold()


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
