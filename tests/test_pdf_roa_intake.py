from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from opencounsel.source.pdf_roa import PdfRoaPackagingError, package_searchable_pdf
from opencounsel.source.roa import inspect_roa_package


def _searchable_pdf(path: Path, texts: tuple[str, ...]) -> Path:
    writer = PdfWriter()
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    font_ref = writer._add_object(font)
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): font_ref}
                )
            }
        )
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as target:
        writer.write(target)
    return path


def test_packages_verified_searchable_pdf_as_a_safe_roa(tmp_path: Path) -> None:
    source = _searchable_pdf(
        tmp_path / "record.pdf",
        ("Synthetic record page one.", "Synthetic record page two."),
    )
    output = tmp_path / "record.zip"

    result = package_searchable_pdf(
        source,
        output,
        first_record_page=40,
        numbering_verified=True,
    )

    inspected = inspect_roa_package(output)
    assert result.page_count == 2
    assert result.first_record_page == 40
    assert (inspected.first_record_page, inspected.last_record_page) == (40, 41)
    assert inspected.pages[0].text == "Synthetic record page one."


def test_pdf_intake_requires_numbering_attestation_and_searchable_text(
    tmp_path: Path,
) -> None:
    source = _searchable_pdf(tmp_path / "record.pdf", ("Synthetic record.",))
    with pytest.raises(PdfRoaPackagingError, match="confirm"):
        package_searchable_pdf(
            source,
            tmp_path / "unverified.zip",
            first_record_page=1,
            numbering_verified=False,
        )

    blank = tmp_path / "blank.pdf"
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    with blank.open("wb") as target:
        writer.write(target)
    with pytest.raises(PdfRoaPackagingError, match="searchable text"):
        package_searchable_pdf(
            blank,
            tmp_path / "blank.zip",
            first_record_page=1,
            numbering_verified=True,
        )


def test_pdf_intake_rejects_invalid_paths_ranges_and_pdf_data(tmp_path: Path) -> None:
    source = _searchable_pdf(tmp_path / "record.pdf", ("Synthetic record.",))
    with pytest.raises(PdfRoaPackagingError, match="positive"):
        package_searchable_pdf(
            source,
            tmp_path / "range.zip",
            first_record_page=0,
            numbering_verified=True,
        )
    with pytest.raises(PdfRoaPackagingError, match="regular PDF"):
        package_searchable_pdf(
            tmp_path / "missing.pdf",
            tmp_path / "missing.zip",
            first_record_page=1,
            numbering_verified=True,
        )

    existing = tmp_path / "existing.zip"
    existing.write_bytes(b"existing")
    with pytest.raises(PdfRoaPackagingError, match="new ZIP"):
        package_searchable_pdf(
            source,
            existing,
            first_record_page=1,
            numbering_verified=True,
        )

    invalid = tmp_path / "invalid.pdf"
    invalid.write_bytes(b"not a PDF")
    with pytest.raises(PdfRoaPackagingError, match="could not be parsed"):
        package_searchable_pdf(
            invalid,
            tmp_path / "invalid.zip",
            first_record_page=1,
            numbering_verified=True,
        )


def test_pdf_intake_rejects_empty_pdf(tmp_path: Path) -> None:
    empty = tmp_path / "empty.pdf"
    with empty.open("wb") as target:
        PdfWriter().write(target)
    with pytest.raises(PdfRoaPackagingError, match="page count"):
        package_searchable_pdf(
            empty,
            tmp_path / "empty.zip",
            first_record_page=1,
            numbering_verified=True,
        )
