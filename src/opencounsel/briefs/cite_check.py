from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from opencounsel.briefs.audit import audit_brief
from opencounsel.briefs.ir import AuthorityOccurrence, BriefAudit
from opencounsel.briefs.sources import official_source_for
from opencounsel.contracts.models import CorrectionRecord

AUDIT_RULE_ID = "offline-citation-review-v1"


@dataclass(frozen=True, slots=True)
class CitationReviewPlan:
    input_sha256: str
    record_citation_count: int
    resolved_record_citation_count: int
    unresolved_record_citation_count: int
    authority_citation_count: int
    findings: tuple[CorrectionRecord, ...]


def plan_citation_review(source: Path) -> CitationReviewPlan:
    """Create exact review findings without contacting any external service."""
    return citation_review_from_audit(audit_brief(source))


def citation_review_from_audit(
    audit: BriefAudit,
    *,
    record_source_supplied: bool = False,
) -> CitationReviewPlan:
    """Create review findings from one already hash-bound local audit."""
    official_sources = _official_sources(audit)
    findings: list[CorrectionRecord] = []

    for citation in audit.record_citations:
        if citation.resolved:
            physical_pages = ", ".join(
                str(page) for page in citation.physical_pdf_pages if page is not None
            )
            finding_kind = "record-source-resolved"
            note = (
                "Record citation resolved against the supplied ROA to physical PDF "
                f"page(s) {physical_pages}. Source-support review remains pending."
            )
        elif record_source_supplied:
            finding_kind = "record-source-unresolved"
            note = (
                "The supplied ROA does not contain every cited record page; record-source "
                "resolution remains pending."
            )
        else:
            finding_kind = "record-source-missing"
            note = (
                "Record citation detected, but no ROA package was supplied to process_brief; "
                "record-page resolution remains pending."
            )
        findings.append(
            _finding(
                audit.brief_sha256,
                item_type="record-citation",
                finding_kind=finding_kind,
                part=citation.part,
                paragraph_index=citation.paragraph_index,
                start=citation.start,
                end=citation.end,
                text=citation.text,
                note=note,
            )
        )

    for authority in audit.authorities:
        findings.append(
            _authority_finding(audit.brief_sha256, authority, official_sources)
        )

    return CitationReviewPlan(
        input_sha256=audit.brief_sha256,
        record_citation_count=len(audit.record_citations),
        resolved_record_citation_count=sum(
            citation.resolved for citation in audit.record_citations
        ),
        unresolved_record_citation_count=sum(
            not citation.resolved for citation in audit.record_citations
        ),
        authority_citation_count=len(audit.authorities),
        findings=tuple(findings),
    )


def _official_sources(audit: BriefAudit) -> dict[str, tuple[str, str]]:
    sources: dict[str, tuple[str, str]] = {}
    for authority in audit.authorities:
        if not authority.is_canonical_candidate:
            continue
        resolution = official_source_for(authority)
        if resolution is None or resolution.url is None or resolution.status != "verified":
            continue
        sources.setdefault(
            authority.normalized_text.casefold(),
            (resolution.source_type, resolution.url),
        )
    return sources


def _authority_finding(
    input_sha256: str,
    authority: AuthorityOccurrence,
    official_sources: dict[str, tuple[str, str]],
) -> CorrectionRecord:
    canonical = authority.resolved_citation
    if canonical is None and authority.is_canonical_candidate:
        canonical = authority.normalized_text

    if authority.hyperlink_target:
        kind = "authority-existing-licensed-link" if _licensed(authority) else (
            "authority-existing-link"
        )
        note = (
            "Existing subscription-source navigation link preserved. The authority is present, "
            "but a reviewable source copy is still required for substantive verification."
            if _licensed(authority)
            else "Existing navigation link preserved. Link presence does not establish source "
            "identity or substantive verification."
        )
    elif canonical is None:
        kind = "authority-short-form-unresolved"
        note = (
            "Short-form citation has no uniquely approved antecedent; authority identity and "
            "source verification remain pending."
        )
    elif source := official_sources.get(canonical.casefold()):
        kind = "authority-official-source-candidate"
        source_type, url = source
        source_label = (
            "official source candidate"
            if source_type == "official"
            else f"{source_type} source candidate"
        )
        note = (
            f"Deterministic offline resolution found an {source_label} "
            f"({url}). The source was not contacted; the candidate is eligible for reviewed "
            "hyperlink projection."
        )
    elif _licensed(authority):
        kind = "authority-licensed-source-needed"
        note = (
            "Vendor citation and authority identity detected; a licensed or manually supplied "
            "source copy is required for substantive verification. No source was contacted and "
            "citation accuracy remains pending."
        )
    else:
        kind = "authority-source-needed"
        canonical_note = (
            f" The short form was locally reconciled to {canonical}."
            if authority.resolved_citation
            else ""
        )
        note = (
            "The authority was detected, but no deterministic offline source candidate was found. "
            "Use a private source override or an explicit citation-only resolver; source and "
            "citation accuracy remain pending."
            f"{canonical_note}"
        )

    return _finding(
        input_sha256,
        item_type="authority-citation",
        finding_kind=kind,
        part=authority.part,
        paragraph_index=authority.paragraph_index,
        start=authority.start,
        end=authority.end,
        text=authority.text,
        note=note,
    )


def _licensed(authority: AuthorityOccurrence) -> bool:
    normalized = authority.normalized_text.casefold()
    return authority.citation_type == "VendorCaseCitation" or any(
        marker in normalized for marker in (" lexis ", " wl ")
    )


def _finding(
    input_sha256: str,
    *,
    item_type: Literal["record-citation", "authority-citation"],
    finding_kind: str,
    part: str,
    paragraph_index: int,
    start: int,
    end: int,
    text: str,
    note: str,
) -> CorrectionRecord:
    payload = {
        "input_sha256": input_sha256,
        "rule_id": AUDIT_RULE_ID,
        "item_type": item_type,
        "finding_kind": finding_kind,
        "part": part,
        "paragraph_index": paragraph_index,
        "start_offset": start,
        "end_offset": end,
        "original_text": text,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return CorrectionRecord(
        correction_id=f"corr-{digest}",
        stage="cite-check",
        item_type=item_type,
        basis_sha256=input_sha256,
        part=part,
        paragraph_index=paragraph_index,
        start_offset=start,
        end_offset=end,
        original_text=text,
        replacement_text=text,
        note=note,
        application_status="review-only",
        review_status="pending",
    )
