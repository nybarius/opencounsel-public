from __future__ import annotations

import json
import os
import subprocess
import tempfile
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

from pypdf import PdfReader

from opencounsel.briefs.audit import audit_brief
from opencounsel.briefs.link_docx import apply_authority_links
from opencounsel.briefs.links import AuthorityResolution, plan_authority_links
from opencounsel.source.authority_package import (
    dispose_pdf_link_annotations,
    extract_pdf_link_annotations,
)
from opencounsel.web.jobs import JobContext, JobManager, SourceFinalizationError

WORD_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def prepare_link_disposition(
    manager: JobManager,
    job_id: str,
    authority_ids: Sequence[str],
) -> dict[str, object]:
    """Record PDF link candidates after source identity verification."""
    context = manager._context(job_id)
    with manager._lock:
        state = manager._read_state(context)
        if state.get("source_verification") is None:
            raise SourceFinalizationError(
                "Authority links can be reviewed only after source identity verification."
            )
        finalization = context.job_dir / "source-finalization"
        intake = finalization / "bundle" / "source-intake"
        links: list[dict[str, object]] = []
        malformed_annotation_count = 0
        for authority_id in authority_ids:
            extraction = extract_pdf_link_annotations(
                intake / f"{authority_id}.pdf",
                authority_id=authority_id,
            )
            disposed = dispose_pdf_link_annotations(
                extraction,
                approved_link_ids=set(),
                source_identity_verified=True,
            )
            raw_links = disposed.get("links")
            if not isinstance(raw_links, list):
                raise SourceFinalizationError("The PDF link review manifest is invalid.")
            links.extend(
                dict(item) for item in raw_links if isinstance(item, Mapping)
            )
            malformed_annotation_count += _nonnegative_int(
                disposed.get("malformed_annotation_count")
            )

        disposition = _disposition_payload(
            links,
            malformed_annotation_count=malformed_annotation_count,
        )
        disposition_path = finalization / "private-link-disposition.json"
        _write_json_new(disposition_path, disposition)
        final_package = finalization / "final-review-package.zip"
        _rewrite_final_package(
            final_package,
            disposition_path=disposition_path,
        )
        artifacts = dict(cast(Mapping[str, object], state.get("artifacts", {})))
        artifacts["link-disposition"] = _artifact_record(
            context,
            disposition_path,
            "application/json",
        )
        manager._update_state(
            context,
            link_disposition=disposition,
            artifacts=artifacts,
            message=(
                "Sources verified; review extracted PDF links before creating linked copies"
            ),
        )
        return cast(dict[str, object], manager._read_state(context))


def approve_link_disposition(
    manager: JobManager,
    job_id: str,
    link_ids: Sequence[str],
) -> dict[str, object]:
    """Approve declared durable candidates and create separate linked artifacts."""
    context = manager._context(job_id)
    with manager._lock:
        state = manager._read_state(context)
        raw_disposition = state.get("link_disposition")
        if not isinstance(raw_disposition, Mapping):
            raise SourceFinalizationError(
                "Link approval requires a completed source-link review."
            )
        raw_links = raw_disposition.get("links")
        if not isinstance(raw_links, list):
            raise SourceFinalizationError("The PDF link review manifest is invalid.")
        links = [dict(item) for item in raw_links if isinstance(item, Mapping)]
        if len(links) != len(raw_links):
            raise SourceFinalizationError("The PDF link review manifest is invalid.")

        selected = set(link_ids)
        known_ids = {
            str(link["link_id"])
            for link in links
            if isinstance(link.get("link_id"), str)
        }
        if not selected <= known_ids:
            raise SourceFinalizationError(
                "Link approval references an undeclared candidate."
            )
        selected_links = [link for link in links if link.get("link_id") in selected]
        if any(
            link.get("classification") != "durable-candidate"
            for link in selected_links
        ):
            raise SourceFinalizationError(
                "Only eligible durable link candidates may be approved."
            )
        authority_ids = [
            str(link["authority_id"])
            for link in selected_links
            if isinstance(link.get("authority_id"), str)
        ]
        if len(authority_ids) != len(selected_links):
            raise SourceFinalizationError("The PDF link review manifest is invalid.")
        if len(set(authority_ids)) != len(authority_ids):
            raise SourceFinalizationError(
                "Approve no more than one durable link candidate for each authority."
            )

        finalization = context.job_dir / "source-finalization"
        linked_docx = finalization / "linked-document.docx"
        linked_pdf = finalization / "linked-document.pdf"
        if (
            linked_docx.exists()
            or linked_docx.is_symlink()
            or linked_pdf.exists()
            or linked_pdf.is_symlink()
        ):
            raise SourceFinalizationError(
                "Approved link artifacts have already been created."
            )

        approved = dispose_pdf_link_annotations(
            dict(raw_disposition),
            approved_link_ids=selected,
            source_identity_verified=True,
        )
        approved_links = approved.get("links")
        if not isinstance(approved_links, list):
            raise SourceFinalizationError("The PDF link review manifest is invalid.")
        disposition = _disposition_payload(
            [dict(item) for item in approved_links if isinstance(item, Mapping)],
            malformed_annotation_count=_nonnegative_int(
                approved.get("malformed_annotation_count")
            ),
        )

        manifest = _load_json(
            finalization / "bundle" / "authority-manifest.json",
            "The declared authority manifest is unavailable.",
        )
        resolutions = _approved_resolutions(manifest, selected_links)
        published_docx = context.job_dir / "export" / "published.docx"
        plan = plan_authority_links(audit_brief(published_docx), resolutions)
        result = apply_authority_links(published_docx, linked_docx, plan)
        approved_urls = {
            str(link["normalized_candidate_url"])
            for link in selected_links
            if isinstance(link.get("normalized_candidate_url"), str)
        }
        inserted_urls = {item.url for item in result.inserted}
        if not approved_urls <= inserted_urls:
            linked_docx.unlink(missing_ok=True)
            raise SourceFinalizationError(
                "An approved link could not be projected onto its declared citation."
            )

        try:
            _render_pdf(linked_docx, linked_pdf, manager.libreoffice)
            disposition_path = finalization / "private-link-disposition.json"
            _write_json_replace(disposition_path, disposition)
            final_package = finalization / "final-review-package.zip"
            _rewrite_final_package(
                final_package,
                disposition_path=disposition_path,
                linked_docx=linked_docx,
                linked_pdf=linked_pdf,
            )
        except Exception:
            linked_docx.unlink(missing_ok=True)
            linked_pdf.unlink(missing_ok=True)
            raise

        artifacts = dict(cast(Mapping[str, object], state.get("artifacts", {})))
        artifacts.update(
            {
                "link-disposition": _artifact_record(
                    context,
                    disposition_path,
                    "application/json",
                ),
                "linked-document": _artifact_record(
                    context,
                    linked_docx,
                    WORD_MEDIA_TYPE,
                ),
                "linked-pdf": _artifact_record(
                    context,
                    linked_pdf,
                    "application/pdf",
                ),
            }
        )
        manager._update_state(
            context,
            link_disposition=disposition,
            artifacts=artifacts,
            message="Approved durable links inserted into separate final artifacts",
        )
        return cast(dict[str, object], manager._read_state(context))


def _disposition_payload(
    links: list[dict[str, object]],
    *,
    malformed_annotation_count: int,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "source_identity_verified": True,
        "candidate_count": sum(
            link.get("classification") == "durable-candidate" for link in links
        ),
        "approved_link_count": sum(
            link.get("approval_status") == "approved" for link in links
        ),
        "malformed_annotation_count": malformed_annotation_count,
        "links": links,
    }


def _approved_resolutions(
    manifest: Mapping[str, Any],
    selected_links: Sequence[Mapping[str, object]],
) -> tuple[AuthorityResolution, ...]:
    raw_authorities = manifest.get("authorities")
    if not isinstance(raw_authorities, list):
        raise SourceFinalizationError("The declared authority manifest is unavailable.")
    authorities = {
        item.get("authority_id"): item
        for item in raw_authorities
        if isinstance(item, Mapping) and isinstance(item.get("authority_id"), str)
    }
    values: list[AuthorityResolution] = []
    seen: set[tuple[str, str]] = set()
    for link in selected_links:
        authority_id = link.get("authority_id")
        url = link.get("normalized_candidate_url")
        authority = authorities.get(authority_id)
        if not isinstance(authority, Mapping) or not isinstance(url, str):
            raise SourceFinalizationError(
                "Link approval does not match a declared authority."
            )
        for citation in _citation_keys(authority):
            key = (citation.casefold(), url)
            if key in seen:
                continue
            seen.add(key)
            values.append(
                AuthorityResolution(
                    citation,
                    "verified",
                    url,
                    "local-source-override",
                    "licensed-or-manual",
                )
            )
    if not values:
        raise SourceFinalizationError(
            "Approved links do not identify a citation in the authority manifest."
        )
    return tuple(values)


def _citation_keys(authority: Mapping[str, object]) -> tuple[str, ...]:
    values: list[str] = []
    raw_assertions = authority.get("assertions")
    if isinstance(raw_assertions, list):
        for assertion in raw_assertions:
            if not isinstance(assertion, Mapping):
                continue
            citation = assertion.get("citation_text")
            if isinstance(citation, str) and citation.strip():
                values.append(citation.strip())
    canonical = authority.get("canonical_citation")
    if isinstance(canonical, str) and canonical.strip():
        values.append(canonical.strip())
    return tuple(dict.fromkeys(values))


def _render_pdf(source: Path, output: Path, executable: str) -> None:
    with tempfile.TemporaryDirectory(
        prefix="link-render-",
        dir=output.parent,
    ) as temporary:
        root = Path(temporary)
        profile = root / "profile"
        converted = root / f"{source.stem}.pdf"
        result = subprocess.run(
            [
                executable,
                "--headless",
                "--nologo",
                "--nodefault",
                "--norestore",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(root),
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 or not converted.is_file():
            raise SourceFinalizationError("LibreOffice could not render the linked PDF.")
        try:
            reader = PdfReader(converted)
            if reader.is_encrypted or not reader.pages:
                raise SourceFinalizationError("The linked PDF is encrypted or empty.")
        except SourceFinalizationError:
            raise
        except Exception as exc:
            raise SourceFinalizationError("The linked PDF is invalid.") from exc
        os.replace(converted, output)
        output.chmod(0o600)


def _rewrite_final_package(
    output: Path,
    *,
    disposition_path: Path,
    linked_docx: Path | None = None,
    linked_pdf: Path | None = None,
) -> None:
    if not output.is_file() or output.is_symlink():
        raise SourceFinalizationError("The final review package is unavailable.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".final-links.",
        suffix=".zip",
        dir=output.parent,
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    replaced = {
        "review/private-link-disposition.json",
        "final/linked-document.docx",
        "final/linked-document.pdf",
    }
    try:
        with zipfile.ZipFile(output) as incoming, zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as outgoing:
            for member in incoming.infolist():
                if member.filename in replaced:
                    continue
                outgoing.writestr(member, incoming.read(member.filename))
            outgoing.write(disposition_path, "review/private-link-disposition.json")
            if linked_docx is not None and linked_pdf is not None:
                outgoing.write(linked_docx, "final/linked-document.docx")
                outgoing.write(linked_pdf, "final/linked-document.pdf")
        os.replace(temporary, output)
        output.chmod(0o600)
    except (OSError, zipfile.BadZipFile) as exc:
        raise SourceFinalizationError(
            "The final review package could not be updated."
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_record(
    context: JobContext,
    path: Path,
    media_type: str,
) -> dict[str, str]:
    return {
        "path": path.relative_to(context.job_dir).as_posix(),
        "filename": path.name,
        "media_type": media_type,
    }


def _load_json(path: Path, message: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceFinalizationError(message) from exc
    if not isinstance(value, dict):
        raise SourceFinalizationError(message)
    return cast(dict[str, Any], value)


def _write_json_new(path: Path, payload: Mapping[str, object]) -> None:
    if path.exists() or path.is_symlink():
        raise SourceFinalizationError("The PDF link review manifest already exists.")
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        path.chmod(0o600)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _write_json_replace(path: Path, payload: Mapping[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".link-disposition.",
        suffix=".json",
        dir=path.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _nonnegative_int(value: object) -> int:
    return value if isinstance(value, int) and value >= 0 else 0


__all__ = ["approve_link_disposition", "prepare_link_disposition"]
