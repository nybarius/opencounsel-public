from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from opencounsel.source.roa import (
    RoaValidationError,
    inspect_roa_package,
    normalize_record_cite,
)


def test_inspects_synthetic_package(roa_package: Path) -> None:
    package = inspect_roa_package(roa_package)

    assert len(package.pages) == 3
    assert (package.first_record_page, package.last_record_page) == (3, 5)
    assert package.pages[0].physical_page == 1
    assert package.pages[0].display_cite == "R 3"
    assert package.pdf.member_name == "indexed.pdf"
    assert [value.status for value in package.validations] == ["pass", "pass", "pass", "warning"]


@pytest.mark.parametrize("cite", ["R 3", "R. 3", " r  3 "])
def test_normalizes_record_cites(cite: str) -> None:
    assert normalize_record_cite(cite) == 3


def test_rejects_bad_cite() -> None:
    with pytest.raises(RoaValidationError, match="form"):
        normalize_record_cite("page 3")


def test_rejects_path_traversal(tmp_path: Path) -> None:
    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../pages.jsonl", "{}")
        archive.writestr("map.csv", "x")
        archive.writestr("indexed.pdf", "x")
    with pytest.raises(RoaValidationError, match="unsafe member path"):
        inspect_roa_package(package)


def test_rejects_locator_mismatch(roa_package: Path, tmp_path: Path) -> None:
    changed = tmp_path / "changed.zip"
    with zipfile.ZipFile(roa_package) as source, zipfile.ZipFile(changed, "w") as target:
        for member in source.infolist():
            data = source.read(member)
            if member.filename.endswith(".jsonl"):
                lines = data.decode().splitlines()
                row = json.loads(lines[0])
                row["record_cite"] = "R 99"
                lines[0] = json.dumps(row)
                data = ("\n".join(lines) + "\n").encode()
            target.writestr(member.filename, data)
    with pytest.raises(RoaValidationError, match="cite mismatch"):
        inspect_roa_package(changed)


def test_rejects_nonfile_and_missing_required_member(tmp_path: Path) -> None:
    with pytest.raises(RoaValidationError, match="regular"):
        inspect_roa_package(tmp_path)
    package = tmp_path / "missing.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("pages.jsonl", "{}")
    with pytest.raises(RoaValidationError, match=r"exactly one \.csv"):
        inspect_roa_package(package)


def test_rejects_invalid_pdf(roa_package: Path, tmp_path: Path) -> None:
    changed = _replace_member(roa_package, tmp_path / "bad-pdf.zip", ".pdf", b"not a pdf")
    with pytest.raises(RoaValidationError, match="PDF member"):
        inspect_roa_package(changed)


def test_rejects_csv_count_mismatch(roa_package: Path, tmp_path: Path) -> None:
    changed = _replace_member(
        roa_package,
        tmp_path / "bad-csv.zip",
        ".csv",
        b"pdf_page,record_page,record_cite,printed_top_center_number,verified_original_number\n",
    )
    with pytest.raises(RoaValidationError, match="page counts differ"):
        inspect_roa_package(changed)


def test_rejects_empty_jsonl(roa_package: Path, tmp_path: Path) -> None:
    changed = _replace_member(roa_package, tmp_path / "empty.zip", ".jsonl", b"")
    with pytest.raises(RoaValidationError, match="no pages"):
        inspect_roa_package(changed)


def _replace_member(source_path: Path, target_path: Path, suffix: str, replacement: bytes) -> Path:
    with zipfile.ZipFile(source_path) as source, zipfile.ZipFile(target_path, "w") as target:
        for member in source.infolist():
            data = replacement if member.filename.endswith(suffix) else source.read(member)
            target.writestr(member.filename, data)
    return target_path
