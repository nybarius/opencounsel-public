from __future__ import annotations

import csv
import json
import stat
import zipfile
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from opencounsel.briefs.audit import audit_brief
from opencounsel.briefs.authority_manifest import (
    build_authority_acquisition_manifest,
    write_authority_acquisition_manifest,
)
from opencounsel.source.authority_package import (
    AuthorityPackageError,
    build_authority_package,
)
from opencounsel.source.authority_verify import verify_authority_package


def _text_pdf(path: Path, text: str) -> Path:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {
            NameObject("/Font"): DictionaryObject(
                {NameObject("/F1"): writer._add_object(font)}
            )
        }
    )
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode())
    page[NameObject("/Contents")] = writer._add_object(stream)
    with path.open("wb") as output:
        writer.write(output)
    return path


def _bundle(tmp_path: Path) -> tuple[Path, str]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    brief = tmp_path / "brief.docx"
    document = Document()
    document.add_paragraph(
        'Smith v. Jones, 2026 N.Y. Misc. LEXIS 1234, held that "the agreement is unambiguous."'
    )
    document.save(brief)
    manifest = build_authority_acquisition_manifest(audit_brief(brief))
    bundle = tmp_path / "bundle"
    paths = write_authority_acquisition_manifest(manifest, bundle)
    authority_id = manifest.authorities[0].authority_id
    _text_pdf(
        bundle / "smith.pdf",
        "Smith v. Jones. 2026 N.Y. Misc. LEXIS 1234. "
        "The agreement is unambiguous. Judgment affirmed.",
    )
    rows: list[dict[str, str]] = []
    with paths[2].open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    rows[0]["source_file"] = "smith.pdf"
    with paths[2].open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    return bundle, authority_id


def test_packages_authority_pdf_and_runs_deterministic_verification(tmp_path: Path) -> None:
    bundle, authority_id = _bundle(tmp_path)
    package = tmp_path / "authorities.zip"

    result = build_authority_package(bundle, package)
    report = tmp_path / "verification.json"
    summary = verify_authority_package(package, report)

    assert result.source_count == 1
    assert result.page_count == 1
    assert not result.missing_authority_ids
    assert stat.S_IMODE(package.stat().st_mode) == 0o600
    assert summary == {
        "authority_count": 1,
        "source_present_count": 1,
        "citation_confirmed_count": 1,
        "assertion_count": 1,
        "quotation_failure_count": 0,
        "characterization_review_count": 1,
    }
    payload = json.loads(report.read_text(encoding="utf-8"))
    authority = payload["authorities"][0]
    assert authority["authority_id"] == authority_id
    assert authority["citation_exists"] == "pass"
    assert authority["assertions"][0]["quotation_exact"] == "pass"
    assert authority["assertions"][0]["likely_pertinent_pages"] == [1]
    with zipfile.ZipFile(package) as archive:
        page = json.loads(archive.read("pages.jsonl"))
    assert page["text_sha256"]
    assert "unambiguous" in page["text"]


def test_partial_package_records_missing_sources(tmp_path: Path) -> None:
    bundle, authority_id = _bundle(tmp_path)
    intake = bundle / "authority-intake.csv"
    text = intake.read_text(encoding="utf-8").replace("smith.pdf", "")
    intake.write_text(text, encoding="utf-8")

    package = tmp_path / "partial.zip"
    result = build_authority_package(bundle, package)
    report = tmp_path / "partial-report.json"
    summary = verify_authority_package(package, report)

    assert result.source_count == 0
    assert result.missing_authority_ids == (authority_id,)
    assert summary["source_present_count"] == 0
    assertion = json.loads(report.read_text(encoding="utf-8"))["authorities"][0]["assertions"][0]
    assert assertion["quotation_exact"] == "blocked-no-source"
    assert assertion["characterization_supported"] == "blocked-no-source"


def test_rejects_escaped_or_unknown_authority_sources(tmp_path: Path) -> None:
    bundle, _authority_id = _bundle(tmp_path)
    intake = bundle / "authority-intake.csv"
    text = intake.read_text(encoding="utf-8").replace("smith.pdf", "../smith.pdf")
    intake.write_text(text, encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="escapes"):
        build_authority_package(bundle, tmp_path / "bad.zip")

    bundle, _authority_id = _bundle(tmp_path / "second")
    intake = bundle / "authority-intake.csv"
    text = intake.read_text(encoding="utf-8").replace("auth-", "unknown-")
    intake.write_text(text, encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="unknown authority"):
        build_authority_package(bundle, tmp_path / "unknown.zip")


def test_rejects_unsafe_verification_package(tmp_path: Path) -> None:
    package = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("../manifest.json", "{}")
    with pytest.raises(AuthorityPackageError, match="unsafe member path"):
        verify_authority_package(package, tmp_path / "report.json")


def test_rejects_missing_bundle_files_existing_output_and_bad_pdf(tmp_path: Path) -> None:
    with pytest.raises(AuthorityPackageError, match="regular directory"):
        build_authority_package(tmp_path / "missing", tmp_path / "out.zip")

    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(AuthorityPackageError, match="authority manifest"):
        build_authority_package(empty, tmp_path / "out.zip")

    bundle, _authority_id = _bundle(tmp_path / "bundle-case")
    existing = tmp_path / "existing.zip"
    existing.touch()
    with pytest.raises(AuthorityPackageError, match="already exists"):
        build_authority_package(bundle, existing)

    (bundle / "smith.pdf").write_text("not a PDF", encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="readable PDF"):
        build_authority_package(bundle, tmp_path / "bad-pdf.zip")


def test_verification_flags_transformed_quote_and_malformed_metadata(tmp_path: Path) -> None:
    bundle, _authority_id = _bundle(tmp_path / "transformed")
    manifest_path = bundle / "authority-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["authorities"][0]["assertions"][0]["context"] = (
        'The court held that "the agreement ... unambiguous [as written]." '
        "(internal quotation marks omitted)."
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = tmp_path / "transformed.zip"
    build_authority_package(bundle, package)
    report = tmp_path / "transformed.json"
    verify_authority_package(package, report)

    assertion = json.loads(report.read_text(encoding="utf-8"))["authorities"][0]["assertions"][0]
    assert assertion["quotation_exact"] == "fail"
    assert assertion["quotation_signals_complete"] == "review-required"
    assert assertion["signals_found"] == ["internal quotation marks omitted"]

    malformed = tmp_path / "malformed.zip"
    with zipfile.ZipFile(malformed, "w") as archive:
        archive.writestr("manifest.json", "not-json")
        archive.writestr("pages.jsonl", "{}\n")
        archive.writestr("brief-authority-manifest.json", '{"schema_version":1}')
    with pytest.raises(AuthorityPackageError, match="package manifest is invalid JSON"):
        verify_authority_package(malformed, tmp_path / "malformed.json")


def test_verification_handles_no_quote_and_rejects_bad_inputs(tmp_path: Path) -> None:
    bundle, _authority_id = _bundle(tmp_path / "no-quote")
    manifest_path = bundle / "authority-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["authorities"][0]["assertions"][0]["context"] = (
        "The court held the agreement unambiguous."
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    package = tmp_path / "no-quote.zip"
    build_authority_package(bundle, package)
    report = tmp_path / "no-quote.json"
    verify_authority_package(package, report)
    assertion = json.loads(report.read_text(encoding="utf-8"))["authorities"][0]["assertions"][0]
    assert assertion["quotation_exact"] == "not-applicable"

    with pytest.raises(AuthorityPackageError, match="regular ZIP"):
        verify_authority_package(tmp_path / "missing.zip", tmp_path / "missing.json")
    with pytest.raises(AuthorityPackageError, match="already exists"):
        verify_authority_package(package, report)
    not_zip = tmp_path / "not.zip"
    not_zip.write_text("bad", encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="readable ZIP"):
        verify_authority_package(not_zip, tmp_path / "bad-report.json")
    incomplete = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(incomplete, "w") as archive:
        archive.writestr("manifest.json", '{"schema_version":1}')
    with pytest.raises(AuthorityPackageError, match="missing required metadata"):
        verify_authority_package(incomplete, tmp_path / "incomplete.json")


def test_rejects_empty_manifest_duplicate_intake_and_non_pdf_source(tmp_path: Path) -> None:
    malformed_bundle, _authority_id = _bundle(tmp_path / "malformed-bundle")
    (malformed_bundle / "authority-manifest.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="invalid JSON"):
        build_authority_package(malformed_bundle, tmp_path / "malformed-bundle.zip")

    bundle, _authority_id = _bundle(tmp_path / "invalid-bundle")
    manifest_path = bundle / "authority-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["authorities"] = []
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="no authorities"):
        build_authority_package(bundle, tmp_path / "empty.zip")

    bundle, _authority_id = _bundle(tmp_path / "duplicate")
    intake = bundle / "authority-intake.csv"
    lines = intake.read_text(encoding="utf-8").splitlines()
    intake.write_text("\n".join([*lines, lines[1]]) + "\n", encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="unique"):
        build_authority_package(bundle, tmp_path / "duplicate.zip")

    bundle, _authority_id = _bundle(tmp_path / "not-pdf")
    intake = bundle / "authority-intake.csv"
    intake.write_text(
        intake.read_text(encoding="utf-8").replace("smith.pdf", "authority.txt"),
        encoding="utf-8",
    )
    (bundle / "authority.txt").write_text("text", encoding="utf-8")
    with pytest.raises(AuthorityPackageError, match="regular PDF"):
        build_authority_package(bundle, tmp_path / "not-pdf.zip")
