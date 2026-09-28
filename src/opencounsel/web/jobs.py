from __future__ import annotations

import csv
import json
import os
import re
import shutil
import tempfile
import threading
import uuid
import zipfile
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from opencounsel.adapters.symbolic_ai import conformance
from opencounsel.briefs.audit import audit_brief
from opencounsel.briefs.authority_manifest import (
    build_authority_acquisition_manifest,
    write_authority_acquisition_manifest,
)
from opencounsel.briefs.clean import clean_brief
from opencounsel.briefs.report import write_brief_audit
from opencounsel.briefs.sources import resolve_authority_sources
from opencounsel.publication.foss import publish_foss, render_docx_reference_pdf
from opencounsel.revisions import RevisionStore
from opencounsel.source.authority_package import build_authority_package
from opencounsel.source.authority_verify import verify_authority_package
from opencounsel.source.roa import inspect_roa_package
from opencounsel.templates.profiles import get_bundled_filing_profile

JOB_ID_RE = re.compile(r"^[0-9a-f]{32}$")
STAGES = (
    ("queued", "Inputs received"),
    ("validating", "Validating brief and record"),
    ("preparing", "Resolving citations and applying filing styles"),
    ("publishing", "Compiling TOC/TOA and rendering output"),
    ("reporting", "Building source and review reports"),
    ("packaging", "Packaging filing and review artifacts"),
    ("completed", "Prepared for lawyer review"),
)

type ProgressUpdate = Callable[[str, str], None]
type JobProcessor = Callable[["JobContext", ProgressUpdate], dict[str, object]]


@dataclass(frozen=True, slots=True)
class JobContext:
    job_id: str
    job_dir: Path
    inbox_dir: Path
    work_dir: Path
    brief_path: Path
    roa_path: Path | None
    profile_id: str


@dataclass(frozen=True, slots=True)
class JobReservation:
    context: JobContext
    record_pdf_path: Path


@dataclass(frozen=True, slots=True)
class Artifact:
    path: Path
    filename: str
    media_type: str


class JobNotFoundError(LookupError):
    pass


class SourceFinalizationError(ValueError):
    pass


class JobManager:
    """Single-user, disk-backed job coordinator for the local web interface."""

    def __init__(
        self,
        root: Path,
        *,
        processor: JobProcessor | None = None,
        libreoffice: str = "libreoffice",
        max_workers: int = 1,
    ) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.libreoffice = libreoffice
        self._processor = processor or self._process
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="opencounsel-job",
        )
        self._lock = threading.RLock()
        self._futures: dict[str, Future[dict[str, object]]] = {}

    def reserve(
        self,
        *,
        profile_id: str,
        brief_name: str,
        roa_name: str | None,
        record_mode: str = "record",
        demo: bool = False,
    ) -> JobReservation:
        if record_mode not in {"record", "no-record"}:
            raise ValueError("unknown record mode")
        profile = get_bundled_filing_profile(profile_id)
        job_id = uuid.uuid4().hex
        job_dir = self.root / job_id
        inbox = job_dir / "inbox"
        work = job_dir / "work"
        for directory in (job_dir, inbox, work):
            directory.mkdir(mode=0o700)
            directory.chmod(0o700)
        context = JobContext(
            job_id=job_id,
            job_dir=job_dir,
            inbox_dir=inbox,
            work_dir=work,
            brief_path=inbox / "brief.docx",
            roa_path=inbox / "record.zip" if record_mode == "record" else None,
            profile_id=profile.profile_id,
        )
        self._write_state(
            context,
            {
                "job_id": job_id,
                "status": "queued",
                "stage": "queued",
                "message": "Inputs received",
                "created_at": datetime.now(UTC).isoformat(),
                "profile": {
                    "profile_id": profile.profile_id,
                    "court": profile.court,
                    "jurisdiction": profile.jurisdiction,
                    "document_type": profile.document_type,
                },
                "brief_name": brief_name,
                "roa_name": roa_name,
                "record_mode": record_mode,
                "demo": demo,
                "stages": self._stage_view("queued"),
                "summary": None,
                "sources": [],
                "audit": {},
                "artifacts": {},
                "error": None,
            },
        )
        return JobReservation(context=context, record_pdf_path=inbox / "record.pdf")

    def submit(self, context: JobContext) -> None:
        with self._lock:
            if context.job_id in self._futures:
                raise ValueError("job has already been submitted")
            self._futures[context.job_id] = self._executor.submit(
                self._execute, context
            )

    def mark_failed(self, context: JobContext, message: str) -> None:
        state = self._read_state(context)
        stage = state.get("stage", "queued")
        active_stage = stage if isinstance(stage, str) else "queued"
        self._update_state(
            context,
            status="failed",
            stage="failed",
            message="Preparation stopped",
            stages=self._failed_stage_view(active_stage),
            error=message,
        )

    def snapshot(self, job_id: str) -> dict[str, object]:
        context = self._context(job_id)
        with self._lock:
            return cast(dict[str, object], self._read_state(context))

    def artifact(self, job_id: str, key: str) -> Artifact:
        context = self._context(job_id)
        state = self._read_state(context)
        artifacts = state.get("artifacts", {})
        if not isinstance(artifacts, Mapping) or key not in artifacts:
            raise JobNotFoundError("artifact was not found")
        raw = artifacts[key]
        if not isinstance(raw, Mapping):
            raise JobNotFoundError("artifact was not found")
        try:
            relative = Path(str(raw["path"]))
            filename = str(raw["filename"])
            media_type = str(raw["media_type"])
        except KeyError as exc:
            raise JobNotFoundError("artifact was not found") from exc
        path = (context.job_dir / relative).resolve()
        if (
            relative.is_absolute()
            or not path.is_relative_to(context.job_dir)
            or not path.is_file()
            or path.is_symlink()
        ):
            raise JobNotFoundError("artifact was not found")
        return Artifact(path=path, filename=filename, media_type=media_type)

    def reserve_source_uploads(
        self,
        job_id: str,
        authority_ids: Sequence[str],
    ) -> dict[str, Path]:
        context = self._context(job_id)
        with self._lock:
            state = self._read_state(context)
            if state.get("status") != "completed":
                raise SourceFinalizationError(
                    "Sources can be added only after preparation completes."
                )
            if state.get("source_verification") is not None:
                raise SourceFinalizationError("An accepted authority source cannot be replaced.")
            declared = _declared_authorities(context)
            unknown = sorted(set(authority_ids) - declared)
            if unknown:
                raise SourceFinalizationError(
                    "Each upload must use an authority ID from the declared authority manifest."
                )
            finalization = context.job_dir / "source-finalization"
            if finalization.exists():
                raise SourceFinalizationError("A source upload is already in progress.")
            bundle = finalization / "bundle"
            intake = bundle / "source-intake"
            intake.mkdir(parents=True, mode=0o700)
            intake.chmod(0o700)
            source_bundle = context.job_dir / "export" / "reports" / "authority-sources"
            _private_copy(
                source_bundle / "authority-manifest.json",
                bundle / "authority-manifest.json",
            )
            _private_copy(
                source_bundle / "authority-intake.csv",
                bundle / "authority-intake.csv",
            )
            return {authority_id: intake / f"{authority_id}.pdf" for authority_id in authority_ids}

    def discard_source_uploads(self, job_id: str) -> None:
        context = self._context(job_id)
        with self._lock:
            shutil.rmtree(context.job_dir / "source-finalization", ignore_errors=True)

    def finalize_sources(
        self,
        job_id: str,
        authority_ids: Sequence[str],
    ) -> dict[str, object]:
        context = self._context(job_id)
        with self._lock:
            finalization = context.job_dir / "source-finalization"
            bundle = finalization / "bundle"
            _bind_source_intake(bundle / "authority-intake.csv", authority_ids)
            authority_package = finalization / "authority-package.zip"
            verification = finalization / "verification.json"
            build_authority_package(bundle, authority_package)
            summary = verify_authority_package(authority_package, verification)
            report = self._read_json(verification)
            _require_identity_matches(report, authority_ids)
            final_package = finalization / "final-review-package.zip"
            _write_final_review_package(
                final_package,
                context.job_dir / "export",
                authority_package,
                verification,
            )
            state = self._read_state(context)
            sources = _verified_source_rows(state.get("sources"), report, authority_ids)
            artifacts = dict(cast(Mapping[str, object], state.get("artifacts", {})))
            artifacts.update(
                {
                    "authority-package": _artifact_record(
                        context, authority_package, "application/zip"
                    ),
                    "verification": _artifact_record(
                        context, verification, "application/json"
                    ),
                    "final-package": _artifact_record(
                        context, final_package, "application/zip"
                    ),
                }
            )
            self._update_state(
                context,
                sources=sources,
                source_verification=summary,
                artifacts=artifacts,
                message="Sources verified; final review package ready",
                finalized_at=datetime.now(UTC).isoformat(),
            )
            return cast(dict[str, object], self._read_state(context))

    def delete(self, job_id: str) -> None:
        context = self._context(job_id)
        with self._lock:
            future = self._futures.get(job_id)
            if future is not None and not future.done():
                raise ValueError("a running job cannot be deleted")
            shutil.rmtree(context.job_dir)
            self._futures.pop(job_id, None)

    def close(self) -> None:
        self._executor.shutdown(wait=True, cancel_futures=False)

    def _execute(self, context: JobContext) -> dict[str, object]:
        try:
            result = self._processor(
                context,
                lambda stage, message: self._progress(context, stage, message),
            )
            self._update_state(
                context,
                **result,
                status="completed",
                stage="completed",
                message="Prepared for lawyer review",
                stages=self._stage_view("completed"),
                error=None,
                completed_at=datetime.now(UTC).isoformat(),
            )
            return result
        except Exception as exc:
            self.mark_failed(context, _safe_error(exc))
            return {"error": _safe_error(exc)}

    def _process(
        self,
        context: JobContext,
        progress: ProgressUpdate,
    ) -> dict[str, object]:
        validation_message = (
            "Validating brief and record"
            if context.roa_path is not None
            else "Validating brief; no record package supplied"
        )
        progress("validating", validation_message)
        if context.roa_path is not None:
            inspect_roa_package(context.roa_path)
        profile = get_bundled_filing_profile(context.profile_id)

        progress("preparing", "Resolving citations and applying filing styles")
        store = RevisionStore(context.work_dir, context.inbox_dir)
        cleaned = clean_brief(
            store,
            context.brief_path,
            context.profile_id,
            roa_package_path=context.roa_path,
        )

        progress("publishing", "Compiling TOC/TOA and rendering output")
        publication = publish_foss(
            store,
            cleaned.process.process_id,
            executable=self.libreoffice,
        )
        delivery = store.deliveries / cleaned.process.process_id
        export = context.job_dir / "export"
        export.mkdir(mode=0o700)
        export.chmod(0o700)
        published_docx = _private_copy(delivery / "published.docx", export / "published.docx")
        published_pdf = _private_copy(delivery / "published.pdf", export / "published.pdf")
        original_pdf = export / "original-brief.pdf"
        render_docx_reference_pdf(
            context.brief_path,
            original_pdf,
            executable=self.libreoffice,
        )
        corrections = _private_copy(
            delivery / "corrections.json", export / "corrections.json"
        )
        publication_json = _private_copy(
            delivery / "publication.json", export / "publication.json"
        )
        front_matter = _private_copy(
            delivery / "front-matter.json", export / "front-matter.json"
        )

        progress("reporting", "Building source and review reports")
        reports = export / "reports"
        corrected, _ledger = store.delivery_paths(cleaned.process.process_id)
        audit = audit_brief(corrected, context.roa_path)
        record_pdf = (
            _extract_record_pdf(context.roa_path, export / "record.pdf")
            if context.roa_path is not None
            else None
        )
        write_brief_audit(
            audit,
            reports,
            record_pdf_name=record_pdf.name if record_pdf is not None else None,
        )
        source_audit = audit_brief(context.brief_path, context.roa_path)
        resolutions = resolve_authority_sources(source_audit)
        authority_manifest = build_authority_acquisition_manifest(
            source_audit, resolutions
        )
        authority_paths = write_authority_acquisition_manifest(
            authority_manifest, reports / "authority-sources"
        )

        # Bind the donor checks to the core's persisted, validated process receipt.
        manifest = store.load_process(cleaned.process.process_id).model_dump(mode="json")
        process_path = export / "process.json"
        conformance_path = export / "symbolic-ai-conformance.json"
        for path, payload in ((process_path, manifest), (conformance_path, conformance(manifest))):
            _write_json_atomic(path, payload)

        progress("packaging", "Packaging filing and review artifacts")
        package = export / "opencounsel-filing-package.zip"
        _write_package(package, export)

        artifacts = {
            "process": _artifact_record(context, process_path, "application/json"),
            "conformance": _artifact_record(context, conformance_path, "application/json"),
            "package": _artifact_record(context, package, "application/zip"),
            "document": _artifact_record(
                context,
                published_docx,
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ),
            "pdf": _artifact_record(context, published_pdf, "application/pdf"),
            "original-pdf": _artifact_record(
                context,
                original_pdf,
                "application/pdf",
            ),
            "corrections": _artifact_record(context, corrections, "application/json"),
            "sources": _artifact_record(context, authority_paths[0], "application/json"),
            "publication": _artifact_record(
                context, publication_json, "application/json"
            ),
            "front-matter": _artifact_record(context, front_matter, "application/json"),
        }
        if record_pdf is not None and context.roa_path is not None:
            artifacts.update(
                {
                    "record": _artifact_record(context, record_pdf, "application/pdf"),
                    "roa-package": _artifact_record(
                        context,
                        context.roa_path,
                        "application/zip",
                        filename="machine-readable-roa.zip",
                    ),
                }
            )

        process = cleaned.process
        return {
            "summary": {
                "record_citation_count": process.record_citation_count,
                "resolved_record_citation_count": process.resolved_record_citation_count,
                "unresolved_record_citation_count": process.unresolved_record_citation_count,
                "toa_authority_count": process.toa_authority_count,
                "toa_occurrence_count": process.toa_occurrence_count,
                "toc_entry_count": process.toc_entry_count,
                "hyperlink_inserted_count": process.hyperlink_inserted_count,
                "hyperlink_review_item_count": process.hyperlink_review_item_count,
                "review_item_count": process.review_item_count,
                "formatting_applied_count": cleaned.formatting_applied_count,
                "source_copy_required_count": authority_manifest.source_copy_required_count,
                "unresolved_authority_occurrence_count": (
                    authority_manifest.unresolved_occurrence_count
                ),
                "page_count": publication.page_count,
                "body_font_pt": profile.typography.body_min_pt,
                "footnote_font_pt": profile.typography.footnote_min_pt,
            },
            "sources": [
                {
                    "authority_id": item.authority_id,
                    "citation": item.canonical_citation,
                    "category": item.category,
                    "status": (
                        "source-copy-required"
                        if item.source_status == "source-needed"
                        else "official-or-open-source"
                    ),
                    "url": item.source_url,
                    "occurrence_count": len(item.assertions),
                }
                for item in authority_manifest.authorities
            ],
            "audit": {
                "input_sha256": process.input_sha256,
                "output_docx_sha256": publication.output_docx_sha256,
                "output_pdf_sha256": publication.output_pdf_sha256,
                "process_id": process.process_id,
                "engine": publication.engine,
                "engine_version": publication.engine_version,
            },
            "artifacts": artifacts,
        }

    def _progress(self, context: JobContext, stage: str, message: str) -> None:
        if stage not in {item[0] for item in STAGES}:
            raise ValueError("unknown job stage")
        self._update_state(
            context,
            status="processing",
            stage=stage,
            message=message,
            stages=self._stage_view(stage),
        )

    def _context(self, job_id: str) -> JobContext:
        if not JOB_ID_RE.fullmatch(job_id):
            raise JobNotFoundError("job was not found")
        job_dir = (self.root / job_id).resolve()
        if not job_dir.is_relative_to(self.root) or not job_dir.is_dir():
            raise JobNotFoundError("job was not found")
        state = self._read_json(job_dir / "state.json")
        profile = state.get("profile", {})
        if not isinstance(profile, Mapping) or not isinstance(
            profile.get("profile_id"), str
        ):
            raise JobNotFoundError("job was not found")
        record_mode = state.get("record_mode", "record")
        if record_mode not in {"record", "no-record"}:
            raise JobNotFoundError("job was not found")
        return JobContext(
            job_id=job_id,
            job_dir=job_dir,
            inbox_dir=job_dir / "inbox",
            work_dir=job_dir / "work",
            brief_path=job_dir / "inbox" / "brief.docx",
            roa_path=(
                job_dir / "inbox" / "record.zip" if record_mode == "record" else None
            ),
            profile_id=cast(str, profile["profile_id"]),
        )

    def _stage_view(self, current: str) -> list[dict[str, str]]:
        ids = [stage for stage, _label in STAGES]
        current_index = ids.index(current) if current in ids else -1
        values: list[dict[str, str]] = []
        for index, (stage, label) in enumerate(STAGES):
            status = "pending"
            if index < current_index:
                status = "completed"
            elif index == current_index:
                status = "active" if stage != "completed" else "completed"
            values.append({"id": stage, "label": label, "status": status})
        return values

    def _failed_stage_view(self, current: str) -> list[dict[str, str]]:
        values = self._stage_view(current)
        for value in values:
            if value["status"] == "active":
                value["status"] = "failed"
        return values

    def _state_path(self, context: JobContext) -> Path:
        return context.job_dir / "state.json"

    def _write_state(self, context: JobContext, state: Mapping[str, object]) -> None:
        with self._lock:
            _write_json_atomic(self._state_path(context), state)

    def _update_state(self, context: JobContext, **changes: object) -> None:
        with self._lock:
            state = self._read_state(context)
            state.update(changes)
            _write_json_atomic(self._state_path(context), state)

    def _read_state(self, context: JobContext) -> dict[str, Any]:
        return self._read_json(self._state_path(context))

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JobNotFoundError("job was not found") from exc
        if not isinstance(value, dict):
            raise JobNotFoundError("job was not found")
        return cast(dict[str, Any], value)


def _extract_record_pdf(package: Path, output: Path) -> Path:
    with zipfile.ZipFile(package) as archive:
        matches = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
        if len(matches) != 1:
            raise ValueError("ROA package does not contain exactly one record PDF")
        data = archive.read(matches[0])
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
    return output


def _declared_authorities(context: JobContext) -> set[str]:
    path = context.job_dir / "export" / "reports" / "authority-sources" / "authority-manifest.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceFinalizationError("The declared authority manifest is unavailable.") from exc
    authorities = value.get("authorities") if isinstance(value, dict) else None
    if not isinstance(authorities, list):
        raise SourceFinalizationError("The declared authority manifest is unavailable.")
    return {
        authority_id
        for item in authorities
        if isinstance(item, dict)
        and isinstance((authority_id := item.get("authority_id")), str)
    }


def _bind_source_intake(path: Path, authority_ids: Sequence[str]) -> None:
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        fieldnames = reader.fieldnames
        rows = list(reader)
    if fieldnames is None or "source_file" not in fieldnames:
        raise SourceFinalizationError("The authority intake ledger is unavailable.")
    selected = set(authority_ids)
    found: set[str] = set()
    for row in rows:
        authority_id = row.get("authority_id", "")
        if authority_id in selected:
            row["source_file"] = f"source-intake/{authority_id}.pdf"
            found.add(authority_id)
    if found != selected:
        raise SourceFinalizationError("Each upload must use a declared authority ID.")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".authority-intake.", suffix=".csv", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _require_identity_matches(
    report: Mapping[str, object], authority_ids: Sequence[str]
) -> None:
    raw = report.get("authorities")
    authorities = raw if isinstance(raw, list) else []
    results = {
        item.get("authority_id"): item
        for item in authorities
        if isinstance(item, dict) and isinstance(item.get("authority_id"), str)
    }
    mismatched = [
        authority_id
        for authority_id in authority_ids
        if results.get(authority_id, {}).get("citation_exists") != "pass"
    ]
    if mismatched:
        raise SourceFinalizationError(
            "The uploaded PDF does not match its declared authority citation or case name."
        )


def _verified_source_rows(
    raw_sources: object,
    report: Mapping[str, object],
    authority_ids: Sequence[str],
) -> list[dict[str, object]]:
    sources = (
        [dict(item) for item in raw_sources if isinstance(item, Mapping)]
        if isinstance(raw_sources, list)
        else []
    )
    raw_results = report.get("authorities")
    results = {
        item.get("authority_id"): item
        for item in raw_results
        if isinstance(item, dict) and isinstance(item.get("authority_id"), str)
    } if isinstance(raw_results, list) else {}
    selected = set(authority_ids)
    for source in sources:
        authority_id = source.get("authority_id")
        if authority_id not in selected:
            continue
        result = results.get(authority_id, {})
        assertions = result.get("assertions")
        assertion_rows = assertions if isinstance(assertions, list) else []
        quotation_states = {
            assertion.get("quotation_exact")
            for assertion in assertion_rows
            if isinstance(assertion, dict)
        }
        source.update(
            {
                "status": "verified-source",
                "identity_result": "confirmed",
                "quotation_result": "fail" if "fail" in quotation_states else "pass",
                "characterization_result": "lawyer-review-required",
            }
        )
    return sources


def _write_final_review_package(
    output: Path,
    export: Path,
    authority_package: Path,
    verification: Path,
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".final-review.", suffix=".zip", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.rglob("*")):
                if path.is_file() and not path.is_symlink():
                    member = Path("first-pass") / path.relative_to(export)
                    archive.write(path, member.as_posix())
            archive.write(authority_package, "sources/authority-package.zip")
            archive.write(verification, "review/verification.json")
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _private_copy(source: Path, output: Path) -> Path:
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with source.open("rb") as reader, os.fdopen(descriptor, "wb") as writer:
        shutil.copyfileobj(reader, writer)
    return output


def _write_package(output: Path, export: Path) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".filing-package.", suffix=".zip", dir=export
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(export.rglob("*")):
                if not path.is_file() or path in {output, temporary} or path.is_symlink():
                    continue
                archive.write(path, path.relative_to(export).as_posix())
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def _artifact_record(
    context: JobContext,
    path: Path,
    media_type: str,
    *,
    filename: str | None = None,
) -> dict[str, str]:
    return {
        "path": path.relative_to(context.job_dir).as_posix(),
        "filename": filename or path.name,
        "media_type": media_type,
    }


def _write_json_atomic(path: Path, payload: Mapping[str, object]) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".state.", suffix=".json", dir=path.parent
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


def _safe_error(exc: Exception) -> str:
    message = str(exc).strip().replace("\r", " ").replace("\n", " ")
    if not message or len(message) > 500:
        return "OpenCounsel could not prepare this filing. Review the input files and try again."
    return message


__all__ = [
    "Artifact",
    "JobContext",
    "JobManager",
    "JobNotFoundError",
    "JobReservation",
    "ProgressUpdate",
    "SourceFinalizationError",
]
