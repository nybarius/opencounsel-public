from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Never

from opencounsel.briefs.docx import BriefDocxError, inspect_brief_docx
from opencounsel.briefs.ir import BriefAudit
from opencounsel.briefs.link_docx import LinkProjectionError, apply_authority_links
from opencounsel.briefs.links import LinkInsertion, plan_authority_links
from opencounsel.briefs.sources import SourceOverride, resolve_authority_sources
from opencounsel.contracts.models import CorrectionRecord

LINK_RULE_ID = "offline-allowlisted-authority-links-v1"


@dataclass(frozen=True, slots=True)
class OfflineHyperlinkResult:
    input_sha256: str
    output_sha256: str
    corrections: tuple[CorrectionRecord, ...]
    candidate_count: int
    inserted_count: int
    review_count: int


def project_authority_links(
    source: Path,
    output: Path,
    audit: BriefAudit,
    *,
    overrides: tuple[SourceOverride, ...] = (),
) -> OfflineHyperlinkResult:
    """Project deterministic official or caller-verified links without network access."""
    inspection = inspect_brief_docx(source)
    if inspection.sha256 != audit.brief_sha256:
        raise LinkProjectionError("citation audit does not match the hyperlink input")
    resolutions = resolve_authority_sources(
        audit,
        overrides=overrides,
        use_courtlistener=False,
        opener=_deny_network,
    )
    plan = plan_authority_links(audit, resolutions)
    candidates = plan.insertions

    if not candidates:
        _copy_exact(source, output)
        return OfflineHyperlinkResult(
            inspection.sha256,
            inspection.sha256,
            (),
            0,
            0,
            0,
        )

    if _is_signed(source):
        _copy_exact(source, output)
        signed_corrections = tuple(
            _record(
                inspection.sha256,
                insertion,
                "review-only",
                "digitally signed package was not changed",
            )
            for insertion in candidates
        )
        return OfflineHyperlinkResult(
            inspection.sha256,
            inspection.sha256,
            signed_corrections,
            len(candidates),
            0,
            len(candidates),
        )

    applied = apply_authority_links(source, output, plan)
    inserted = set(applied.inserted)
    review_reasons = {
        (item.part, item.paragraph_index, item.start, item.end, item.citation): item.reason
        for item in applied.review
        if item.start is not None and item.end is not None
    }
    decisions: list[CorrectionRecord] = []
    for insertion in candidates:
        if insertion in inserted:
            decisions.append(_record(inspection.sha256, insertion, "applied"))
            continue
        key = (
            insertion.part,
            insertion.paragraph_index,
            insertion.start,
            insertion.end,
            insertion.expected_text,
        )
        decisions.append(
            _record(
                inspection.sha256,
                insertion,
                "review-only",
                review_reasons.get(key, "the conservative Word projector abstained"),
            )
        )
    return OfflineHyperlinkResult(
        inspection.sha256,
        applied.output_sha256,
        tuple(decisions),
        len(candidates),
        len(inserted),
        len(candidates) - len(inserted),
    )


def project_offline_authority_links(
    source: Path,
    output: Path,
    audit: BriefAudit,
) -> OfflineHyperlinkResult:
    """Preserve the original offline-only public API."""
    return project_authority_links(source, output, audit)


def _record(
    basis_sha256: str,
    insertion: LinkInsertion,
    status: Literal["applied", "review-only"],
    reason: str | None = None,
) -> CorrectionRecord:
    payload = {
        "basis_sha256": basis_sha256,
        "rule_id": LINK_RULE_ID,
        "part": insertion.part,
        "paragraph_index": insertion.paragraph_index,
        "start_offset": insertion.start,
        "end_offset": insertion.end,
        "original_text": insertion.expected_text,
        "url": insertion.url,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    note = (
        f"Inserted allowlisted {insertion.source_type} hyperlink from "
        f"{insertion.resolver} ({insertion.url}); review the target in Word."
        if reason is None
        else f"Eligible allowlisted hyperlink was not inserted automatically: {reason}."
    )
    return CorrectionRecord(
        correction_id=f"corr-{digest}",
        stage="hyperlink",
        item_type="hyperlink",
        basis_sha256=basis_sha256,
        part=insertion.part,
        paragraph_index=insertion.paragraph_index,
        start_offset=insertion.start,
        end_offset=insertion.end,
        original_text=insertion.expected_text,
        replacement_text=insertion.expected_text,
        note=note,
        application_status=status,
        review_status="pending",
    )


def _copy_exact(source: Path, output: Path) -> None:
    if source.resolve() == output.resolve():
        raise LinkProjectionError("link projection must write a new DOCX")
    if output.exists() or output.is_symlink():
        raise LinkProjectionError("link projection output already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".docx", dir=output.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as writer:
            descriptor = -1
            with source.open("rb") as reader:
                shutil.copyfileobj(reader, writer)
                writer.flush()
                os.fsync(writer.fileno())
        temporary.chmod(0o600)
        os.replace(temporary, output)
        output.chmod(0o600)
    except (OSError, shutil.Error) as exc:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)
        raise LinkProjectionError("unchanged hyperlink projection could not be written") from exc


def _is_signed(source: Path) -> bool:
    try:
        with zipfile.ZipFile(source) as archive:
            return any(name.startswith("_xmlsignatures/") for name in archive.namelist())
    except (OSError, zipfile.BadZipFile) as exc:
        raise BriefDocxError("DOCX is not a readable OOXML package") from exc


def _deny_network(*_args: object, **_kwargs: object) -> Never:
    raise LinkProjectionError("network access is disabled for offline hyperlink projection")
