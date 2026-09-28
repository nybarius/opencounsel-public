from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from opencounsel.briefs.normalize_docx import normalize_brief_formatting
from opencounsel.briefs.sources import SourceOverride
from opencounsel.contracts.models import CleanBriefResult
from opencounsel.revisions import RevisionStore


def clean_brief(
    revisions: RevisionStore,
    source: Path,
    profile_id: str,
    *,
    roa_package_path: Path | None = None,
    authority_overrides: tuple[SourceOverride, ...] = (),
) -> CleanBriefResult:
    """Run the complete deterministic brief-preparation pipeline."""
    source_revision = revisions.create(source)
    roa_source = (
        revisions.confine_support(
            roa_package_path,
            suffix=".zip",
            label="ROA package",
        )
        if roa_package_path is not None
        else None
    )
    with tempfile.TemporaryDirectory(prefix="clean-brief-", dir=revisions.root) as temporary:
        staging = Path(temporary)
        normalized_path = staging / "normalized.docx"
        formatting = normalize_brief_formatting(source, normalized_path, profile_id)
        staged_roa: Path | None = None
        if roa_source is not None:
            staged_roa = staging / "record-source.zip"
            shutil.copyfile(roa_source, staged_roa)
            staged_roa.chmod(0o600)
        normalized_store = RevisionStore(revisions.root, staging)
        normalized_revision = normalized_store.create(normalized_path)
        process = normalized_store.process(
            normalized_revision.revision_id,
            roa_package_path=staged_roa,
            authority_overrides=authority_overrides,
        )
    return CleanBriefResult(
        profile_id=profile_id,
        source_revision_id=source_revision.revision_id,
        normalized_revision_id=normalized_revision.revision_id,
        formatting_applied_count=formatting.applied_count,
        authority_link_inserted_count=process.hyperlink_inserted_count,
        authority_link_review_count=process.hyperlink_review_item_count,
        process=process,
    )


__all__ = ["clean_brief"]
