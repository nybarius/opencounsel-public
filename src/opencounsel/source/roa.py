from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from pypdf import PdfReader

from opencounsel.source.ir import Artifact, RoaPackage, SourcePage, Validation

MAX_MEMBERS = 16
MAX_MEMBER_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 250 * 1024 * 1024
MAX_COMPRESSION_RATIO = 200
CITE_RE = re.compile(r"^R\.?\s*(\d+)$", re.IGNORECASE)


class RoaValidationError(ValueError):
    """Raised when an ingestion package fails a deterministic safety or integrity check."""


def normalize_record_cite(value: str) -> int:
    match = CITE_RE.fullmatch(value.strip())
    if not match:
        raise RoaValidationError("record cite must have the form 'R 123' or 'R. 123'")
    return int(match.group(1))


def inspect_roa_package(path: Path) -> RoaPackage:
    if not path.is_file() or path.is_symlink():
        raise RoaValidationError("package must be a regular, non-symlink file")
    package_sha, package_size = _hash_path(path)
    package_artifact = Artifact(
        "ingestion_bundle", "application/zip", None, package_sha, package_size
    )

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise RoaValidationError("package is not a valid ZIP archive") from exc

    with archive:
        members = _safe_members(archive)
        jsonl = _single_member(members, ".jsonl")
        csv_member = _single_member(members, ".csv")
        pdf_member = _single_member(members, ".pdf")
        pages = _read_pages(archive, jsonl)
        _validate_csv(archive, csv_member, pages)
        pdf_artifact, pdf_pages = _inspect_pdf(archive, pdf_member)
        if pdf_pages != len(pages):
            raise RoaValidationError("PDF and JSONL page counts differ")

    _validate_sequence(pages)
    validations = (
        Validation("safe_archive", "pass", f"{len(members)} members passed archive checks"),
        Validation("locator_alignment", "pass", f"{len(pages)} page locators agree"),
        Validation("pdf_page_count", "pass", f"PDF contains {pdf_pages} pages"),
        Validation(
            "original_source_absent",
            "warning",
            "package contains an indexed derivative; pre-processing original was not supplied",
        ),
    )
    return RoaPackage(package_artifact, pdf_artifact, tuple(pages), validations)


def _safe_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    members = archive.infolist()
    if not members or len(members) > MAX_MEMBERS:
        raise RoaValidationError("archive has an invalid member count")
    names: set[str] = set()
    total = 0
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or not path.name:
            raise RoaValidationError("archive contains an unsafe member path")
        if member.filename in names:
            raise RoaValidationError("archive contains duplicate member names")
        names.add(member.filename)
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise RoaValidationError("archive contains a symbolic link")
        if member.flag_bits & 0x1:
            raise RoaValidationError("encrypted ZIP members are not accepted")
        if member.file_size > MAX_MEMBER_BYTES:
            raise RoaValidationError("archive member exceeds the size limit")
        total += member.file_size
        if member.compress_size == 0 and member.file_size:
            raise RoaValidationError("archive member has an unsafe compression ratio")
        if member.compress_size and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
            raise RoaValidationError("archive member has an unsafe compression ratio")
    if total > MAX_TOTAL_BYTES:
        raise RoaValidationError("archive exceeds the total size limit")
    bad_member = archive.testzip()
    if bad_member is not None:
        raise RoaValidationError("archive member failed its CRC check")
    return members


def _single_member(members: list[zipfile.ZipInfo], suffix: str) -> zipfile.ZipInfo:
    matches = [member for member in members if member.filename.lower().endswith(suffix)]
    if len(matches) != 1:
        raise RoaValidationError(f"archive must contain exactly one {suffix} member")
    return matches[0]


def _read_pages(archive: zipfile.ZipFile, member: zipfile.ZipInfo) -> list[SourcePage]:
    pages: list[SourcePage] = []
    with archive.open(member) as raw:
        for line_number, raw_line in enumerate(raw, start=1):
            try:
                value = json.loads(raw_line)
                physical = int(value["physical_pdf_page"])
                record = int(value["record_page"])
                cite = str(value["record_cite"])
                text = str(value["text"])
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise RoaValidationError(f"invalid JSONL row {line_number}") from exc
            if normalize_record_cite(cite) != record:
                raise RoaValidationError(f"JSONL cite mismatch at row {line_number}")
            if not text.strip():
                raise RoaValidationError(f"empty page text at row {line_number}")
            pages.append(SourcePage(physical, record, cite, text))
    if not pages:
        raise RoaValidationError("JSONL contains no pages")
    return pages


def _validate_csv(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo, pages: list[SourcePage]
) -> None:
    with archive.open(member) as raw:
        text = io.TextIOWrapper(raw, encoding="utf-8-sig", newline="")
        rows = list(csv.DictReader(text))
    if len(rows) != len(pages):
        raise RoaValidationError("CSV and JSONL page counts differ")
    for line_number, (row, page) in enumerate(zip(rows, pages, strict=True), start=2):
        try:
            aligns = (
                int(row["pdf_page"]) == page.physical_page
                and int(row["record_page"]) == page.record_page
                and row["record_cite"] == page.display_cite
                and int(row["printed_top_center_number"]) == page.record_page
                and row["verified_original_number"].strip().lower() in {"1", "true", "yes"}
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RoaValidationError(f"invalid CSV row {line_number}") from exc
        if not aligns:
            raise RoaValidationError(f"CSV locator mismatch at row {line_number}")


def _inspect_pdf(
    archive: zipfile.ZipFile, member: zipfile.ZipInfo
) -> tuple[Artifact, int]:
    with archive.open(member) as raw:
        data = raw.read()
    digest = hashlib.sha256(data).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(data))
        count = len(reader.pages)
    except Exception as exc:  # pypdf exposes several parser exception types across versions
        raise RoaValidationError("PDF member could not be parsed") from exc
    artifact = Artifact("indexed_pdf", "application/pdf", member.filename, digest, len(data))
    return artifact, count


def _validate_sequence(pages: list[SourcePage]) -> None:
    physical = [page.physical_page for page in pages]
    record = [page.record_page for page in pages]
    if physical != list(range(1, len(pages) + 1)):
        raise RoaValidationError("physical PDF pages must be unique and contiguous from 1")
    if record != list(range(record[0], record[0] + len(record))):
        raise RoaValidationError("record pages must be unique and contiguous")


def _hash_path(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size
