from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from opencounsel.adapters.citations import extract_citation_candidates
from opencounsel.briefs.docx import inspect_brief_docx
from opencounsel.briefs.ir import (
    AuthorityOccurrence,
    BriefAudit,
    BriefParagraph,
    RecordCitationOccurrence,
)
from opencounsel.source.roa import inspect_roa_package

RECORD_CITE_RE = re.compile(
    r"(?<![A-Za-z0-9])R\.?\s*(\d+)(?:\s*[-\u2013\u2014]\s*(?:R\.?\s*)?(\d+))?",
    re.IGNORECASE,
)


def audit_brief(brief_path: Path, roa_package_path: Path | None = None) -> BriefAudit:
    inspection = inspect_brief_docx(brief_path)
    record_map: dict[int, int] = {}
    if roa_package_path is not None:
        package = inspect_roa_package(roa_package_path)
        record_map = {page.record_page: page.physical_page for page in package.pages}

    record_citations: list[RecordCitationOccurrence] = []
    authorities: list[AuthorityOccurrence] = []
    for paragraph in inspection.paragraphs:
        record_citations.extend(_record_citations(paragraph, record_map))
        authorities.extend(_authority_citations(paragraph))
    authorities = _resolve_short_forms(authorities)

    return BriefAudit(
        inspection.sha256,
        inspection.size_bytes,
        inspection.headings,
        tuple(record_citations),
        tuple(authorities),
    )


def _record_citations(
    paragraph: BriefParagraph, record_map: dict[int, int]
) -> list[RecordCitationOccurrence]:
    citations: list[RecordCitationOccurrence] = []
    for match in RECORD_CITE_RE.finditer(paragraph.text):
        first = int(match.group(1))
        last = int(match.group(2) or first)
        pages = tuple(range(first, last + 1)) if last >= first else (first, last)
        physical_pages = tuple(record_map.get(page) for page in pages)
        citations.append(
            RecordCitationOccurrence(
                paragraph.part,
                paragraph.paragraph_index,
                match.group(0),
                match.start(),
                match.end(),
                pages,
                physical_pages,
                _sentence_context(paragraph.text, match.start(), match.end()),
            )
        )
    return citations


def _authority_citations(paragraph: BriefParagraph) -> list[AuthorityOccurrence]:
    if not paragraph.text.strip():
        return []
    authorities: list[AuthorityOccurrence] = []
    for candidate in extract_citation_candidates(paragraph.text):
        target = next(
            (
                hyperlink.target
                for hyperlink in paragraph.hyperlinks
                if hyperlink.start < candidate.end and candidate.start < hyperlink.end
            ),
            None,
        )
        authorities.append(
            AuthorityOccurrence(
                paragraph.part,
                paragraph.paragraph_index,
                candidate.text,
                candidate.normalized_text,
                candidate.case_name,
                candidate.start,
                candidate.end,
                candidate.citation_type,
                candidate.category,
                target,
                candidate.groups,
                _sentence_context(paragraph.text, candidate.start, candidate.end),
                toa_display=candidate.toa_display,
            )
        )
    return authorities


def _resolve_short_forms(
    authorities: list[AuthorityOccurrence],
) -> list[AuthorityOccurrence]:
    resolved = list(authorities)
    by_scope: dict[str, list[int]] = {}
    for index, authority in enumerate(authorities):
        by_scope.setdefault(authority.part, []).append(index)

    for indexes in by_scope.values():
        prior_cases: list[AuthorityOccurrence] = []
        last_case_citation: str | None = None
        for index in indexes:
            authority = resolved[index]
            if authority.category != "cases":
                if authority.is_canonical_candidate:
                    last_case_citation = None
                continue
            if authority.is_canonical_candidate:
                authority = replace(
                    authority,
                    resolved_citation=authority.normalized_text,
                    resolution_basis="full-citation",
                )
                resolved[index] = authority
                prior_cases.append(authority)
                last_case_citation = authority.normalized_text
                continue
            if authority.citation_type == "IdCitation" and last_case_citation:
                resolved[index] = replace(
                    authority,
                    resolved_citation=last_case_citation,
                    resolution_basis="immediate-antecedent",
                )
                continue
            if authority.citation_type in {"ShortCaseCitation", "SupraCitation"}:
                matches = _short_case_matches(authority, prior_cases)
                if len(matches) == 1:
                    last_case_citation = matches[0]
                    resolved[index] = replace(
                        authority,
                        resolved_citation=last_case_citation,
                        resolution_basis="unique-prior-full-citation",
                    )
                    continue
            last_case_citation = None
    return resolved


def _short_case_matches(
    short: AuthorityOccurrence,
    prior_cases: list[AuthorityOccurrence],
) -> list[str]:
    groups = dict(short.groups)
    volume = groups.get("volume")
    reporter = groups.get("reporter")
    alias = _name_key(short.case_name)
    matches: list[str] = []
    for candidate in prior_cases:
        candidate_groups = dict(candidate.groups)
        if volume and candidate_groups.get("volume") != volume:
            continue
        if reporter and candidate_groups.get("reporter") != reporter:
            continue
        candidate_name = _name_key(candidate.case_name)
        if alias and candidate_name and alias not in candidate_name and candidate_name not in alias:
            continue
        if not alias and not (volume and reporter):
            continue
        if candidate.normalized_text not in matches:
            matches.append(candidate.normalized_text)
    return matches


def _name_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def _sentence_context(text: str, start: int, end: int) -> str:
    left = max(text.rfind(". ", 0, start), text.rfind("? ", 0, start), text.rfind("! ", 0, start))
    left = 0 if left < 0 else left + 2
    boundaries = [
        position for mark in (". ", "? ", "! ") if (position := text.find(mark, end)) >= 0
    ]
    right = min(boundaries) + 1 if boundaries else len(text)
    context = " ".join(text[left:right].split())
    if len(context) <= 500:
        return context
    local_start = max(0, start - left - 200)
    local_end = min(len(context), end - left + 200)
    return context[local_start:local_end]
