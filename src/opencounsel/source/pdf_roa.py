from __future__ import annotations

import csv
import io
import json
import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from opencounsel.source.roa import MAX_MEMBER_BYTES, MAX_TOTAL_BYTES, inspect_roa_package

MAX_PDF_PAGES = 10_000
MAX_EXTRACTED_PAGE_BYTES = 5 * 1024 * 1024


class PdfRoaPackagingError(ValueError):
    """Raised when a raw PDF cannot become a verified sequential ROA package."""


@dataclass(frozen=True, slots=True)
class PdfRoaPackagingResult:
    output: Path
    page_count: int
    first_record_page: int
    last_record_page: int


def package_searchable_pdf(
    source: Path,
    output: Path,
    *,
    first_record_page: int,
    numbering_verified: bool,
) -> PdfRoaPackagingResult:
    """Package a searchable, consecutively numbered PDF for exact record-cite resolution."""
    if not numbering_verified:
        raise PdfRoaPackagingError(
            "confirm that PDF pages follow the stated record-page numbering"
        )
    if first_record_page < 1:
        raise PdfRoaPackagingError("the first record page must be a positive integer")
    if (
        not source.is_file()
        or source.is_symlink()
        or source.suffix.lower() != ".pdf"
    ):
        raise PdfRoaPackagingError("record input must be a regular PDF file")
    if source.stat().st_size > MAX_MEMBER_BYTES:
        raise PdfRoaPackagingError("record PDF exceeds the 100 MiB intake limit")
    if output.suffix.lower() != ".zip" or output.exists() or output.is_symlink():
        raise PdfRoaPackagingError("record package output must be a new ZIP file")

    try:
        reader = PdfReader(source)
        if reader.is_encrypted:
            raise PdfRoaPackagingError("encrypted record PDFs are not accepted")
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise PdfRoaPackagingError("record PDF has an unsupported page count")
        texts = tuple(_page_text(page, index) for index, page in enumerate(reader.pages, 1))
    except PdfRoaPackagingError:
        raise
    except Exception as exc:
        raise PdfRoaPackagingError("record PDF could not be parsed") from exc

    jsonl = io.StringIO()
    csv_text = io.StringIO(newline="")
    writer = csv.DictWriter(
        csv_text,
        fieldnames=(
            "pdf_page",
            "record_page",
            "record_cite",
            "printed_top_center_number",
            "verified_original_number",
        ),
    )
    writer.writeheader()
    for physical_page, text in enumerate(texts, 1):
        record_page = first_record_page + physical_page - 1
        cite = f"R {record_page}"
        jsonl.write(
            json.dumps(
                {
                    "physical_pdf_page": physical_page,
                    "record_page": record_page,
                    "record_cite": cite,
                    "text": text,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
        writer.writerow(
            {
                "pdf_page": physical_page,
                "record_page": record_page,
                "record_cite": cite,
                "printed_top_center_number": record_page,
                "verified_original_number": "true",
            }
        )
    payloads = {
        "pages.jsonl": jsonl.getvalue().encode("utf-8"),
        "page_map.csv": csv_text.getvalue().encode("utf-8"),
        "text.txt": "\n\f\n".join(texts).encode("utf-8"),
    }
    if source.stat().st_size + sum(map(len, payloads.values())) > MAX_TOTAL_BYTES:
        raise PdfRoaPackagingError("record PDF and extracted text exceed the intake limit")

    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".zip", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(source, "indexed.pdf")
            for name, payload in payloads.items():
                archive.writestr(name, payload)
        inspect_roa_package(temporary)
        os.replace(temporary, output)
        output.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)

    return PdfRoaPackagingResult(
        output=output,
        page_count=len(texts),
        first_record_page=first_record_page,
        last_record_page=first_record_page + len(texts) - 1,
    )


def _page_text(page: object, index: int) -> str:
    try:
        raw = page.extract_text()  # type: ignore[attr-defined]
    except Exception as exc:
        raise PdfRoaPackagingError(
            f"record PDF page {index} could not be text-extracted"
        ) from exc
    text = (raw or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        raise PdfRoaPackagingError(
            f"record PDF page {index} has no searchable text; "
            "OCR or a mapped ROA package is required"
        )
    if len(text.encode("utf-8")) > MAX_EXTRACTED_PAGE_BYTES:
        raise PdfRoaPackagingError(f"record PDF page {index} has too much extracted text")
    return text


__all__ = [
    "PdfRoaPackagingError",
    "PdfRoaPackagingResult",
    "package_searchable_pdf",
]
