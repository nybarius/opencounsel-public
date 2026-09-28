from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import Any

from opencounsel.briefs.ir import BriefAudit


def write_brief_audit(
    audit: BriefAudit,
    output_dir: Path,
    *,
    record_pdf_name: str | None = None,
) -> tuple[Path, Path, Path, Path]:
    output_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with suppress(OSError):
        output_dir.chmod(0o700)

    summary_path = output_dir / "brief-audit.json"
    record_path = output_dir / "record-citations.csv"
    authority_path = output_dir / "authorities.csv"
    heading_path = output_dir / "headings.csv"

    summary = {
        "schema_version": 1,
        "brief_sha256": audit.brief_sha256,
        "brief_size_bytes": audit.brief_size_bytes,
        "heading_count": len(audit.headings),
        "record_citation_count": len(audit.record_citations),
        "unresolved_record_citation_count": audit.unresolved_record_citation_count,
        "authority_count": len(audit.authorities),
        "authority_candidate_count": audit.authority_candidate_count,
        "unlinked_authority_candidate_count": audit.unlinked_authority_count,
    }
    _write_private_text(summary_path, json.dumps(summary, indent=2, sort_keys=True) + "\n")

    _write_private_csv(
        record_path,
        (
            "part",
            "paragraph_index",
            "citation",
            "record_pages",
            "physical_pdf_pages",
            "resolved",
            "pdf_targets",
            "context",
        ),
        (
            (
                citation.part,
                citation.paragraph_index,
                citation.text,
                " ".join(str(page) for page in citation.record_pages),
                " ".join("" if page is None else str(page) for page in citation.physical_pdf_pages),
                citation.resolved,
                " ".join(
                    f"{record_pdf_name}#page={page}"
                    for page in citation.physical_pdf_pages
                    if record_pdf_name and page is not None
                ),
                citation.context,
            )
            for citation in audit.record_citations
        ),
    )
    _write_private_csv(
        authority_path,
        (
            "part",
            "paragraph_index",
            "citation",
            "normalized_citation",
            "case_name",
            "category",
            "citation_type",
            "linked",
            "hyperlink_target",
        ),
        (
            (
                authority.part,
                authority.paragraph_index,
                authority.text,
                authority.normalized_text,
                authority.case_name or "",
                authority.category,
                authority.citation_type,
                authority.hyperlink_target is not None,
                authority.hyperlink_target or "",
            )
            for authority in audit.authorities
        ),
    )
    _write_private_csv(
        heading_path,
        ("part", "paragraph_index", "level", "style_id", "basis", "text"),
        (
            (
                heading.part,
                heading.paragraph_index,
                heading.level,
                heading.style_id or "",
                heading.basis,
                heading.text,
            )
            for heading in audit.headings
        ),
    )
    return summary_path, record_path, authority_path, heading_path


def _write_private_text(path: Path, content: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        stream.write(content)


def _write_private_csv(
    path: Path, fields: tuple[str, ...], rows: Iterable[Iterable[Any]]
) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(fields)
        writer.writerows(rows)
