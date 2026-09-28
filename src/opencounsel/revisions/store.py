from __future__ import annotations

import hashlib
import io
import json
import os
import re
import stat
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from jsonschema import ValidationError
from pydantic import ValidationError as PydanticValidationError

from opencounsel.briefs.audit import audit_brief
from opencounsel.briefs.cite_check import citation_review_from_audit
from opencounsel.briefs.docx import BriefDocxError, inspect_brief_docx
from opencounsel.briefs.front_matter import build_front_matter_source
from opencounsel.briefs.front_matter_docx import project_front_matter_fields
from opencounsel.briefs.hyperlink_stage import project_authority_links
from opencounsel.briefs.ir import BriefInspection
from opencounsel.briefs.proof import plan_proof_corrections
from opencounsel.briefs.proof_docx import apply_proof_corrections
from opencounsel.briefs.sources import SourceOverride
from opencounsel.contracts.models import (
    BriefInspectionResult,
    CorrectionLedger,
    CreateRevisionResult,
    FrontMatterSource,
    ProcessBriefResult,
    ProcessManifest,
    RevisionManifest,
)
from opencounsel.contracts.schema import validate_contract
from opencounsel.objects import ContentAddressedStore, StoredObject

REVISION_ID = re.compile(r"^rev-[0-9a-f]{64}$")
PROCESS_ID = re.compile(r"^proc-[0-9a-f]{64}$")
MAX_MANIFEST_BYTES = 64 * 1024
MAX_LEDGER_BYTES = 4 * 1024 * 1024
MAX_FRONT_MATTER_BYTES = 4 * 1024 * 1024
TRANSFORM_ID: Literal["proof-citation-links-front-matter"] = (
    "proof-citation-links-front-matter"
)
TRANSFORM_VERSION: Literal["1"] = "1"


class RevisionError(ValueError):
    """Raised when revision storage or identity fails closed."""


class RevisionStore:
    """Private, immutable revision storage over content-addressed objects."""

    def __init__(self, root: Path, input_root: Path) -> None:
        self.root = _private_directory(root)
        self.input_root = _existing_directory(input_root, "input root")
        self.objects = ContentAddressedStore(self.root / "objects")
        self.manifests = _private_directory(self.root / "revisions")
        self.processes = _private_directory(self.root / "processes")
        self.deliveries = _private_directory(self.root / "deliveries")

    def create(self, source: Path) -> CreateRevisionResult:
        candidate = self._confined_docx(source)
        stored = self._store_confined(candidate)
        inspection = self._inspect_object(stored.key)
        if stored.sha256 != inspection.sha256 or stored.size_bytes != inspection.size_bytes:
            raise RevisionError("stored object failed its content identity check")

        revision_id = f"rev-{stored.sha256}"
        manifest = RevisionManifest(
            revision_id=revision_id,
            input_sha256=stored.sha256,
            input_size_bytes=stored.size_bytes,
            input_object_key=stored.key,
            created_at=datetime.now(UTC).isoformat(),
        )
        created = self._write_once(manifest)
        if not created:
            existing = self.load(revision_id)
            if (
                existing.input_sha256 != stored.sha256
                or existing.input_size_bytes != stored.size_bytes
                or existing.input_object_key != stored.key
            ):
                raise RevisionError("existing revision manifest does not match its content")
        return CreateRevisionResult(
            revision_id=revision_id,
            input_sha256=stored.sha256,
            input_size_bytes=stored.size_bytes,
            created=created,
        )

    def confine_support(self, source: Path, *, suffix: str, label: str) -> Path:
        """Resolve one non-DOCX input below the configured input root."""
        if source.is_symlink():
            raise RevisionError(f"{label} must not be a symbolic link")
        try:
            candidate = source.resolve(strict=True)
        except OSError as exc:
            raise RevisionError(f"{label} does not exist") from exc
        if not candidate.is_relative_to(self.input_root):
            raise RevisionError(f"{label} is outside the configured input root")
        if not candidate.is_file() or candidate.suffix.lower() != suffix.lower():
            raise RevisionError(f"{label} must be a regular {suffix.upper()} file")
        return candidate

    def load(self, revision_id: str) -> RevisionManifest:
        path = self._manifest_path(revision_id)
        if path.is_symlink() or not path.is_file():
            raise RevisionError("revision does not exist")
        if path.stat().st_size > MAX_MANIFEST_BYTES:
            raise RevisionError("revision manifest exceeds size limit")
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(value, dict):
                raise RevisionError("revision manifest must be a JSON object")
            validate_contract("revision-manifest.schema.json", value)
            manifest = RevisionManifest.model_validate(value)
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValidationError,
            PydanticValidationError,
        ) as exc:
            raise RevisionError("revision manifest is invalid") from exc
        if manifest.revision_id != revision_id:
            raise RevisionError("revision manifest identity does not match its path")
        return manifest

    def inspect(self, revision_id: str) -> BriefInspectionResult:
        manifest = self.load(revision_id)
        inspection = self._inspect_object(manifest.input_object_key)
        if (
            inspection.sha256 != manifest.input_sha256
            or inspection.size_bytes != manifest.input_size_bytes
        ):
            raise RevisionError("revision object does not match its manifest")
        part_counts = dict(Counter(paragraph.part for paragraph in inspection.paragraphs))
        external_links = sum(len(paragraph.hyperlinks) for paragraph in inspection.paragraphs)
        return BriefInspectionResult(
            revision_id=revision_id,
            brief_sha256=inspection.sha256,
            size_bytes=inspection.size_bytes,
            paragraph_count=len(inspection.paragraphs),
            heading_count=len(inspection.headings),
            part_counts=part_counts,
            external_link_count=external_links,
        )

    def process(
        self,
        revision_id: str,
        *,
        roa_package_path: Path | None = None,
        authority_overrides: tuple[SourceOverride, ...] = (),
    ) -> ProcessBriefResult:
        """Run proof, citation audit, links, and explicit-slot Word front matter."""
        revision = self.load(revision_id)
        inspection = self._inspect_object(revision.input_object_key)
        if (
            inspection.sha256 != revision.input_sha256
            or inspection.size_bytes != revision.input_size_bytes
        ):
            raise RevisionError("revision object does not match its manifest")

        roa_package = (
            self.confine_support(
                roa_package_path,
                suffix=".zip",
                label="ROA package",
            )
            if roa_package_path is not None
            else None
        )
        record_source_sha256 = _hash_path(roa_package) if roa_package is not None else None
        authority_resolution_sha256 = _authority_resolution_hash(authority_overrides)
        process_id = _process_id(
            revision_id,
            record_source_sha256=record_source_sha256,
            authority_resolution_sha256=authority_resolution_sha256,
        )
        with tempfile.TemporaryDirectory(prefix="process-", dir=self.root) as temporary:
            source = Path(temporary) / "source.docx"
            proofed_path = Path(temporary) / "proofed.docx"
            linked_path = Path(temporary) / "linked.docx"
            corrected_path = Path(temporary) / "corrected.docx"
            os.link(self.objects.path_for(revision.input_object_key), source)
            try:
                plan = plan_proof_corrections(source)
                proof = apply_proof_corrections(source, proofed_path, plan)
                audit = audit_brief(proofed_path, roa_package)
                citation_review = citation_review_from_audit(
                    audit,
                    record_source_supplied=roa_package is not None,
                )
                hyperlinks = project_authority_links(
                    proofed_path,
                    linked_path,
                    audit,
                    overrides=authority_overrides,
                )
                front_matter_audit = audit_brief(linked_path, roa_package)
                front_matter = build_front_matter_source(front_matter_audit)
                front_matter_body = _contract_body(
                    "front-matter-source.schema.json", front_matter
                )
                if len(front_matter_body) > MAX_FRONT_MATTER_BYTES:
                    raise RevisionError("front-matter source exceeds size limit")
                front_matter_object = self.objects.put_stream(
                    io.BytesIO(front_matter_body)
                )
                front_projection = project_front_matter_fields(
                    linked_path,
                    corrected_path,
                    front_matter,
                )
            except BriefDocxError as exc:
                raise RevisionError(str(exc)) from exc
            corrected_object = self.objects.put_path(corrected_path)
        if corrected_object.sha256 != front_projection.output_sha256:
            raise RevisionError("corrected object failed its content identity check")

        if (
            citation_review.input_sha256 != proof.output_sha256
            or hyperlinks.input_sha256 != proof.output_sha256
            or front_matter.brief_sha256 != hyperlinks.output_sha256
            or front_projection.input_sha256 != hyperlinks.output_sha256
        ):
            raise RevisionError("document stages do not match their declared input hashes")
        corrections = (
            proof.corrections
            + citation_review.findings
            + hyperlinks.corrections
            + front_projection.corrections
        )
        applied_count = (
            proof.applied_count
            + hyperlinks.inserted_count
            + front_projection.applied_count
        )
        review_count = (
            proof.review_count
            + len(citation_review.findings)
            + hyperlinks.review_count
            + front_projection.review_count
        )
        review_status: Literal["not-required", "pending"] = (
            "pending" if corrections else "not-required"
        )
        ledger = CorrectionLedger(
            process_id=process_id,
            source_revision_id=revision_id,
            transform_id=TRANSFORM_ID,
            transform_version=TRANSFORM_VERSION,
            input_sha256=revision.input_sha256,
            record_source_sha256=record_source_sha256,
            authority_resolution_sha256=authority_resolution_sha256,
            proofed_sha256=proof.output_sha256,
            hyperlinked_sha256=hyperlinks.output_sha256,
            corrected_sha256=corrected_object.sha256,
            lawyer_review_status=review_status,
            corrections=corrections,
        )
        ledger_body = _contract_body("correction-ledger.schema.json", ledger)
        ledger_object = self.objects.put_stream(io.BytesIO(ledger_body))
        manifest = ProcessManifest(
            process_id=process_id,
            source_revision_id=revision_id,
            transform_id=TRANSFORM_ID,
            transform_version=TRANSFORM_VERSION,
            input_sha256=revision.input_sha256,
            record_source_sha256=record_source_sha256,
            authority_resolution_sha256=authority_resolution_sha256,
            proofed_sha256=proof.output_sha256,
            hyperlinked_sha256=hyperlinks.output_sha256,
            corrected_sha256=corrected_object.sha256,
            corrected_size_bytes=corrected_object.size_bytes,
            corrected_object_key=corrected_object.key,
            correction_ledger_sha256=ledger_object.sha256,
            correction_ledger_size_bytes=ledger_object.size_bytes,
            correction_ledger_object_key=ledger_object.key,
            front_matter_source_sha256=front_matter_object.sha256,
            front_matter_source_size_bytes=front_matter_object.size_bytes,
            front_matter_source_object_key=front_matter_object.key,
            correction_count=len(corrections),
            applied_correction_count=applied_count,
            review_item_count=review_count,
            record_citation_count=citation_review.record_citation_count,
            resolved_record_citation_count=(
                citation_review.resolved_record_citation_count
            ),
            unresolved_record_citation_count=(
                citation_review.unresolved_record_citation_count
            ),
            authority_citation_count=citation_review.authority_citation_count,
            citation_review_item_count=len(citation_review.findings),
            hyperlink_candidate_count=hyperlinks.candidate_count,
            hyperlink_inserted_count=hyperlinks.inserted_count,
            hyperlink_review_item_count=hyperlinks.review_count,
            toc_entry_count=len(front_matter.toc),
            toa_authority_count=len(front_matter.toa),
            toa_occurrence_count=sum(len(item.locations) for item in front_matter.toa),
            front_matter_field_candidate_count=len(front_projection.corrections),
            front_matter_field_applied_count=front_projection.applied_count,
            front_matter_field_review_item_count=front_projection.review_count,
            toc_field_inserted_count=front_projection.toc_field_inserted_count,
            toa_field_inserted_count=front_projection.toa_field_inserted_count,
            lawyer_review_status=review_status,
            created_at=datetime.now(UTC).isoformat(),
        )
        created = self._write_process_once(manifest)
        effective = manifest if created else self.load_process(process_id)
        _require_same_process(effective, manifest)
        self._materialize(effective)
        result = ProcessBriefResult(
            process_id=effective.process_id,
            source_revision_id=effective.source_revision_id,
            input_sha256=effective.input_sha256,
            record_source_sha256=effective.record_source_sha256,
            authority_resolution_sha256=effective.authority_resolution_sha256,
            proofed_sha256=effective.proofed_sha256,
            hyperlinked_sha256=effective.hyperlinked_sha256,
            corrected_sha256=effective.corrected_sha256,
            corrected_size_bytes=effective.corrected_size_bytes,
            correction_ledger_sha256=effective.correction_ledger_sha256,
            correction_ledger_size_bytes=effective.correction_ledger_size_bytes,
            front_matter_source_sha256=effective.front_matter_source_sha256,
            front_matter_source_size_bytes=effective.front_matter_source_size_bytes,
            correction_count=effective.correction_count,
            applied_correction_count=effective.applied_correction_count,
            review_item_count=effective.review_item_count,
            record_citation_count=effective.record_citation_count,
            resolved_record_citation_count=effective.resolved_record_citation_count,
            unresolved_record_citation_count=effective.unresolved_record_citation_count,
            authority_citation_count=effective.authority_citation_count,
            citation_review_item_count=effective.citation_review_item_count,
            hyperlink_candidate_count=effective.hyperlink_candidate_count,
            hyperlink_inserted_count=effective.hyperlink_inserted_count,
            hyperlink_review_item_count=effective.hyperlink_review_item_count,
            toc_entry_count=effective.toc_entry_count,
            toa_authority_count=effective.toa_authority_count,
            toa_occurrence_count=effective.toa_occurrence_count,
            front_matter_field_candidate_count=effective.front_matter_field_candidate_count,
            front_matter_field_applied_count=effective.front_matter_field_applied_count,
            front_matter_field_review_item_count=(
                effective.front_matter_field_review_item_count
            ),
            toc_field_inserted_count=effective.toc_field_inserted_count,
            toa_field_inserted_count=effective.toa_field_inserted_count,
            lawyer_review_status=effective.lawyer_review_status,
            created=created,
        )
        validate_contract("process-brief-result.schema.json", result.model_dump(mode="json"))
        return result

    def load_process(self, process_id: str) -> ProcessManifest:
        path = self._process_path(process_id)
        value = _load_contract_file(path, MAX_MANIFEST_BYTES, "process manifest")
        try:
            validate_contract("process-manifest.schema.json", value)
            manifest = ProcessManifest.model_validate(value)
        except (ValidationError, PydanticValidationError) as exc:
            raise RevisionError("process manifest is invalid") from exc
        if manifest.process_id != process_id:
            raise RevisionError("process manifest identity does not match its path")
        return manifest

    def load_correction_ledger(self, process_id: str) -> CorrectionLedger:
        manifest = self.load_process(process_id)
        value = self._load_object_contract(
            manifest.correction_ledger_object_key,
            manifest.correction_ledger_sha256,
            manifest.correction_ledger_size_bytes,
            MAX_LEDGER_BYTES,
            "correction ledger",
        )
        try:
            validate_contract("correction-ledger.schema.json", value)
            ledger = CorrectionLedger.model_validate(value)
        except (ValidationError, PydanticValidationError) as exc:
            raise RevisionError("correction ledger is invalid") from exc
        if (
            ledger.process_id != process_id
            or ledger.source_revision_id != manifest.source_revision_id
            or ledger.input_sha256 != manifest.input_sha256
            or ledger.record_source_sha256 != manifest.record_source_sha256
            or (
                ledger.authority_resolution_sha256
                != manifest.authority_resolution_sha256
            )
            or ledger.proofed_sha256 != manifest.proofed_sha256
            or ledger.hyperlinked_sha256 != manifest.hyperlinked_sha256
            or ledger.corrected_sha256 != manifest.corrected_sha256
            or len(ledger.corrections) != manifest.correction_count
            or sum(
                item.application_status == "applied" for item in ledger.corrections
            )
            != manifest.applied_correction_count
            or sum(
                item.application_status == "review-only" for item in ledger.corrections
            )
            != manifest.review_item_count
            or sum(item.stage == "cite-check" for item in ledger.corrections)
            != manifest.citation_review_item_count
            or sum(item.item_type == "record-citation" for item in ledger.corrections)
            != manifest.record_citation_count
            or sum(item.item_type == "authority-citation" for item in ledger.corrections)
            != manifest.authority_citation_count
            or sum(item.stage == "hyperlink" for item in ledger.corrections)
            != manifest.hyperlink_candidate_count
            or sum(
                item.stage == "hyperlink" and item.application_status == "applied"
                for item in ledger.corrections
            )
            != manifest.hyperlink_inserted_count
            or sum(
                item.stage == "hyperlink" and item.application_status == "review-only"
                for item in ledger.corrections
            )
            != manifest.hyperlink_review_item_count
            or sum(item.stage in {"toc", "toa"} for item in ledger.corrections)
            != manifest.front_matter_field_candidate_count
            or sum(
                item.stage in {"toc", "toa"} and item.application_status == "applied"
                for item in ledger.corrections
            )
            != manifest.front_matter_field_applied_count
            or sum(
                item.stage in {"toc", "toa"}
                and item.application_status == "review-only"
                for item in ledger.corrections
            )
            != manifest.front_matter_field_review_item_count
            or ledger.lawyer_review_status != manifest.lawyer_review_status
        ):
            raise RevisionError("correction ledger does not match its process manifest")
        return ledger

    def load_front_matter_source(self, process_id: str) -> FrontMatterSource:
        manifest = self.load_process(process_id)
        if (
            manifest.front_matter_source_object_key is None
            or manifest.front_matter_source_sha256 is None
        ):
            raise RevisionError("front-matter source is not available for this process")
        value = self._load_object_contract(
            manifest.front_matter_source_object_key,
            manifest.front_matter_source_sha256,
            manifest.front_matter_source_size_bytes,
            MAX_FRONT_MATTER_BYTES,
            "front-matter source",
        )
        try:
            validate_contract("front-matter-source.schema.json", value)
            source = FrontMatterSource.model_validate(value)
        except (ValidationError, PydanticValidationError) as exc:
            raise RevisionError("front-matter source is invalid") from exc
        if (
            source.brief_sha256 != manifest.hyperlinked_sha256
            or len(source.toc) != manifest.toc_entry_count
            or len(source.toa) != manifest.toa_authority_count
            or sum(len(item.locations) for item in source.toa)
            != manifest.toa_occurrence_count
        ):
            raise RevisionError("front-matter source does not match its process manifest")
        return source

    def delivery_paths(self, process_id: str) -> tuple[Path, Path]:
        manifest = self.load_process(process_id)
        self.load_correction_ledger(process_id)
        directory = self.deliveries / process_id
        corrected = directory / "corrected.docx"
        ledger = directory / "corrections.json"
        _require_artifact(corrected, manifest.corrected_sha256)
        _require_artifact(ledger, manifest.correction_ledger_sha256)
        return corrected, ledger

    def front_matter_path(self, process_id: str) -> Path:
        manifest = self.load_process(process_id)
        self.load_front_matter_source(process_id)
        if manifest.front_matter_source_sha256 is None:
            raise RevisionError("front-matter source is not available for this process")
        path = self.deliveries / process_id / "front-matter.json"
        _require_artifact(path, manifest.front_matter_source_sha256)
        return path

    def _store_confined(self, source: Path) -> StoredObject:
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(source, flags)
        except OSError as exc:
            raise RevisionError("source could not be opened safely") from exc
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise RevisionError("source must be a regular DOCX file")
            with os.fdopen(descriptor, "rb") as stream:
                descriptor = -1
                return self.objects.put_stream(stream)
        finally:
            if descriptor >= 0:
                os.close(descriptor)

    def _inspect_object(self, key: str) -> BriefInspection:
        path = self.objects.path_for(key)
        if path.is_symlink() or not path.is_file():
            raise RevisionError("revision object does not exist")
        with tempfile.TemporaryDirectory(prefix="inspect-", dir=self.root) as temporary:
            alias = Path(temporary) / "brief.docx"
            os.link(path, alias)
            try:
                return inspect_brief_docx(alias)
            except BriefDocxError as exc:
                raise RevisionError(str(exc)) from exc

    def _confined_docx(self, source: Path) -> Path:
        if source.is_symlink():
            raise RevisionError("source must not be a symbolic link")
        try:
            candidate = source.resolve(strict=True)
        except OSError as exc:
            raise RevisionError("source does not exist") from exc
        if not candidate.is_relative_to(self.input_root):
            raise RevisionError("source is outside the configured input root")
        if not candidate.is_file() or candidate.suffix.lower() != ".docx":
            raise RevisionError("source must be a regular DOCX file")
        return candidate

    def _manifest_path(self, revision_id: str) -> Path:
        if not REVISION_ID.fullmatch(revision_id):
            raise RevisionError("revision id is invalid")
        return self.manifests / f"{revision_id}.json"

    def _process_path(self, process_id: str) -> Path:
        if not PROCESS_ID.fullmatch(process_id):
            raise RevisionError("process id is invalid")
        return self.processes / f"{process_id}.json"

    def _write_once(self, manifest: RevisionManifest) -> bool:
        destination = self._manifest_path(manifest.revision_id)
        payload = manifest.model_dump(mode="json")
        validate_contract("revision-manifest.schema.json", payload)
        body = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
        fd, temporary_name = tempfile.mkstemp(prefix="manifest-", dir=self.manifests)
        temporary = Path(temporary_name)
        try:
            if fchmod := getattr(os, "fchmod", None):
                fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, destination)
                destination.chmod(0o600)
                return True
            except FileExistsError:
                return False
        finally:
            temporary.unlink(missing_ok=True)

    def _write_process_once(self, manifest: ProcessManifest) -> bool:
        destination = self._process_path(manifest.process_id)
        body = _contract_body("process-manifest.schema.json", manifest)
        return _link_bytes_once(destination, body)

    def _load_object_contract(
        self,
        key: str,
        expected_sha256: str,
        expected_size: int,
        maximum_size: int,
        label: str,
    ) -> dict[str, object]:
        path = self.objects.path_for(key)
        if path.is_symlink() or not path.is_file():
            raise RevisionError(f"{label} object does not exist")
        if path.stat().st_size != expected_size or expected_size > maximum_size:
            raise RevisionError(f"{label} object has an invalid size")
        body = path.read_bytes()
        if hashlib.sha256(body).hexdigest() != expected_sha256:
            raise RevisionError(f"{label} object does not match its manifest")
        try:
            value = json.loads(body)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RevisionError(f"{label} is invalid") from exc
        if not isinstance(value, dict):
            raise RevisionError(f"{label} must be a JSON object")
        return value

    def _materialize(self, manifest: ProcessManifest) -> None:
        directory = self.deliveries / manifest.process_id
        if directory.is_symlink():
            raise RevisionError("delivery directory must not be a symbolic link")
        directory.mkdir(mode=0o700, exist_ok=True)
        directory.chmod(0o700)
        _copy_once(
            self.objects.path_for(manifest.corrected_object_key),
            directory / "corrected.docx",
            manifest.corrected_sha256,
        )
        _copy_once(
            self.objects.path_for(manifest.correction_ledger_object_key),
            directory / "corrections.json",
            manifest.correction_ledger_sha256,
        )
        if (
            manifest.front_matter_source_object_key is not None
            and manifest.front_matter_source_sha256 is not None
        ):
            _copy_once(
                self.objects.path_for(manifest.front_matter_source_object_key),
                directory / "front-matter.json",
                manifest.front_matter_source_sha256,
            )


def _private_directory(path: Path) -> Path:
    if path.is_symlink():
        raise RevisionError("private storage root must not be a symbolic link")
    try:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
    except OSError as exc:
        raise RevisionError("private storage root must be a directory") from exc
    if not path.is_dir():
        raise RevisionError("private storage root must be a directory")
    path.chmod(0o700)
    return path.resolve()


def _existing_directory(path: Path, label: str) -> Path:
    if path.is_symlink():
        raise RevisionError(f"{label} must not be a symbolic link")
    try:
        candidate = path.resolve(strict=True)
    except OSError as exc:
        raise RevisionError(f"{label} does not exist") from exc
    if not candidate.is_dir() or not stat.S_ISDIR(candidate.stat().st_mode):
        raise RevisionError(f"{label} must be a directory")
    return candidate


def _process_id(
    revision_id: str,
    *,
    record_source_sha256: str | None = None,
    authority_resolution_sha256: str | None = None,
) -> str:
    body = json.dumps(
        {
            "operation": "process-brief",
            "source_revision_id": revision_id,
            "record_source_sha256": record_source_sha256,
            "authority_resolution_sha256": authority_resolution_sha256,
            "transform_id": TRANSFORM_ID,
            "transform_version": TRANSFORM_VERSION,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"proc-{hashlib.sha256(body).hexdigest()}"


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _authority_resolution_hash(
    overrides: tuple[SourceOverride, ...],
) -> str | None:
    if not overrides:
        return None
    payload = [
        {
            "citation": item.citation,
            "url": item.url,
            "note": item.note,
        }
        for item in sorted(overrides, key=lambda value: value.citation.casefold())
    ]
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(body).hexdigest()


def _contract_body(
    schema_name: str,
    model: RevisionManifest | ProcessManifest | CorrectionLedger | FrontMatterSource,
) -> bytes:
    payload = model.model_dump(mode="json")
    validate_contract(schema_name, payload)
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _load_contract_file(path: Path, maximum_size: int, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RevisionError(f"{label} does not exist")
    if path.stat().st_size > maximum_size:
        raise RevisionError(f"{label} exceeds size limit")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RevisionError(f"{label} is invalid") from exc
    if not isinstance(value, dict):
        raise RevisionError(f"{label} must be a JSON object")
    return value


def _link_bytes_once(destination: Path, body: bytes) -> bool:
    fd, temporary_name = tempfile.mkstemp(prefix="manifest-", dir=destination.parent)
    temporary = Path(temporary_name)
    try:
        if fchmod := getattr(os, "fchmod", None):
            fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination)
            destination.chmod(0o600)
            return True
        except FileExistsError:
            return False
    finally:
        temporary.unlink(missing_ok=True)


def _copy_once(source: Path, destination: Path, expected_sha256: str) -> None:
    if destination.exists() or destination.is_symlink():
        _require_artifact(destination, expected_sha256)
        return
    fd, temporary_name = tempfile.mkstemp(prefix="delivery-", dir=destination.parent)
    temporary = Path(temporary_name)
    digest = hashlib.sha256()
    try:
        if fchmod := getattr(os, "fchmod", None):
            fchmod(fd, 0o600)
        with source.open("rb") as reader, os.fdopen(fd, "wb") as writer:
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if digest.hexdigest() != expected_sha256:
            raise RevisionError("stored artifact does not match its process manifest")
        try:
            os.link(temporary, destination)
            destination.chmod(0o600)
        except FileExistsError:
            _require_artifact(destination, expected_sha256)
    finally:
        temporary.unlink(missing_ok=True)


def _require_artifact(path: Path, expected_sha256: str) -> None:
    if path.is_symlink() or not path.is_file():
        raise RevisionError("delivery artifact is missing or unsafe")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise RevisionError("delivery artifact does not match its process manifest")


def _require_same_process(existing: ProcessManifest, expected: ProcessManifest) -> None:
    ignored = {"created_at"}
    existing_payload = existing.model_dump(mode="json", exclude=ignored)
    expected_payload = expected.model_dump(mode="json", exclude=ignored)
    if existing_payload != expected_payload:
        raise RevisionError("existing process manifest does not match this transform")
