from __future__ import annotations

import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, select
from sqlalchemy.orm import Session, aliased

from opencounsel.objects import ContentAddressedStore
from opencounsel.persistence.models import (
    Document,
    IngestionRun,
    Locator,
    LocatorScheme,
    Matter,
    Page,
    Representation,
    SourceFile,
    ValidationResult,
)
from opencounsel.source.ir import Validation
from opencounsel.source.roa import RoaValidationError, inspect_roa_package, normalize_record_cite

OPAQUE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


class ConflictError(ValueError):
    pass


class NotFoundError(LookupError):
    pass


@dataclass(frozen=True, slots=True)
class ImportResult:
    document_id: uuid.UUID
    page_count: int
    first_record_page: int
    last_record_page: int
    package_sha256: str
    warnings: tuple[str, ...]
    already_present: bool


@dataclass(frozen=True, slots=True)
class Resolution:
    document_id: uuid.UUID
    display_cite: str
    normalized_cite: str
    physical_page: int


def make_engine(database_url: str) -> Engine:
    return create_engine(database_url, echo=False)


def import_roa(
    session: Session,
    store: ContentAddressedStore,
    package_path: Path,
    *,
    matter_slug: str,
    document_key: str,
    expected_range: tuple[int, int] | None = None,
) -> ImportResult:
    _validate_key("matter", matter_slug)
    _validate_key("document", document_key)
    package = inspect_roa_package(package_path)
    if expected_range and (
        package.first_record_page != expected_range[0]
        or package.last_record_page != expected_range[1]
    ):
        raise ConflictError("validated record-page range does not match --expect")

    existing = session.scalar(
        select(Document)
        .join(Matter, Document.matter_id == Matter.id)
        .where(Matter.slug == matter_slug, Document.document_key == document_key)
    )
    if existing is not None:
        pdf_source = aliased(SourceFile)
        bundle_source = aliased(SourceFile)
        existing_hashes = session.execute(
            select(pdf_source.sha256, bundle_source.sha256)
            .join(Representation, Representation.source_file_id == pdf_source.id)
            .join(bundle_source, pdf_source.parent_id == bundle_source.id)
            .where(
                Representation.document_id == existing.id,
                pdf_source.role == "indexed_pdf",
                bundle_source.role == "ingestion_bundle",
            )
        ).one()
        if existing_hashes != (package.pdf.sha256, package.package.sha256):
            raise ConflictError("document key already refers to different source bytes")
        return ImportResult(
            existing.id,
            len(package.pages),
            package.first_record_page,
            package.last_record_page,
            package.package.sha256,
            _warnings(package.validations),
            True,
        )

    bundle_object = store.put_path(package_path)
    pdf_member = package.pdf.member_name
    if pdf_member is None:
        raise RoaValidationError("validated ROA PDF has no package member")
    with zipfile.ZipFile(package_path) as archive, archive.open(pdf_member) as pdf_stream:
        pdf_object = store.put_stream(pdf_stream)

    matter = session.scalar(select(Matter).where(Matter.slug == matter_slug))
    if matter is None:
        matter = Matter(slug=matter_slug)
        session.add(matter)
        session.flush()

    bundle = SourceFile(
        matter_id=matter.id,
        role="ingestion_bundle",
        provenance_status="received",
        media_type=package.package.media_type,
        sha256=bundle_object.sha256,
        size_bytes=bundle_object.size_bytes,
        object_key=bundle_object.key,
    )
    session.add(bundle)
    session.flush()
    pdf_source_file = SourceFile(
        matter_id=matter.id,
        parent_id=bundle.id,
        role="indexed_pdf",
        provenance_status="derived_original_absent",
        media_type=package.pdf.media_type,
        sha256=pdf_object.sha256,
        size_bytes=pdf_object.size_bytes,
        object_key=pdf_object.key,
    )
    session.add(pdf_source_file)
    session.flush()

    document = Document(matter_id=matter.id, document_key=document_key, kind="record_on_appeal")
    session.add(document)
    session.flush()
    representation = Representation(
        document_id=document.id,
        source_file_id=pdf_source_file.id,
        kind="indexed_pdf_text",
        extractor="machine_readable_roa_zip",
    )
    session.add(representation)
    session.flush()
    scheme = LocatorScheme(document_id=document.id, name="record_page", prefix="R")
    session.add(scheme)
    session.flush()
    for source_page in package.pages:
        page = Page(
            representation_id=representation.id,
            ordinal=source_page.physical_page,
            text=source_page.text,
        )
        session.add(page)
        session.flush()
        session.add(
            Locator(
                scheme_id=scheme.id,
                page_id=page.id,
                value=source_page.record_page,
                normalized=f"R {source_page.record_page}",
                display=source_page.display_cite,
            )
        )

    run = IngestionRun(matter_id=matter.id, package_source_file_id=bundle.id, status="completed")
    session.add(run)
    session.flush()
    session.add_all(
        ValidationResult(
            ingestion_run_id=run.id,
            code=validation.code,
            status=validation.status,
            detail=validation.detail,
        )
        for validation in package.validations
    )
    session.commit()
    return ImportResult(
        document.id,
        len(package.pages),
        package.first_record_page,
        package.last_record_page,
        package.package.sha256,
        _warnings(package.validations),
        False,
    )


def resolve(session: Session, *, matter_slug: str, document_key: str, cite: str) -> Resolution:
    _validate_key("matter", matter_slug)
    _validate_key("document", document_key)
    value = normalize_record_cite(cite)
    row = session.execute(
        select(Document.id, Locator.display, Locator.normalized, Page.ordinal)
        .join(Matter, Document.matter_id == Matter.id)
        .join(LocatorScheme, LocatorScheme.document_id == Document.id)
        .join(Locator, Locator.scheme_id == LocatorScheme.id)
        .join(Page, Page.id == Locator.page_id)
        .where(
            Matter.slug == matter_slug,
            Document.document_key == document_key,
            LocatorScheme.name == "record_page",
            Locator.value == value,
        )
    ).one_or_none()
    if row is None:
        raise NotFoundError("record cite was not found")
    return Resolution(row.id, row.display, row.normalized, row.ordinal)


def _validate_key(kind: str, value: str) -> None:
    if not OPAQUE_KEY_RE.fullmatch(value):
        raise ValueError(f"{kind} key must be an opaque ASCII identifier")


def _warnings(validations: tuple[Validation, ...]) -> tuple[str, ...]:
    return tuple(value.code for value in validations if value.status == "warning")
