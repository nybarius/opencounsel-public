from __future__ import annotations

import json
import stat
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

import pytest
from pypdf import PdfWriter
from pypdf.generic import RectangleObject

from opencounsel.source import authority_package
from opencounsel.source.authority_package import AuthorityPackageError


def _api(name: str) -> Callable[..., dict[str, object] | Path]:
    function = getattr(authority_package, name, None)
    assert callable(function), f"{name} is not implemented"
    return cast(Callable[..., dict[str, object] | Path], function)


def _pdf(path: Path, urls: tuple[str, ...] = (), *, password: str | None = None) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    for index, url in enumerate(urls):
        writer.add_uri(
            0,
            url,
            RectangleObject((10, 10 + index * 20, 120, 20 + index * 20)),
        )
    if password is not None:
        writer.encrypt(password)
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def test_unproven_non_http_and_fragment_targets_are_never_candidates(
    tmp_path: Path,
) -> None:
    source = _pdf(
        tmp_path / "mixed-links.pdf",
        (
            "javascript:alert(1)",
            "https://law.example/opinions/123",
            "https://law.example/opinions/123.pdf#page=2",
        ),
    )
    extraction = cast(
        dict[str, object],
        _api("extract_pdf_link_annotations")(source, authority_id="auth-mixed"),
    )
    links = cast(list[dict[str, Any]], extraction["links"])

    assert [link["classification"] for link in links] == [
        "invalid-target",
        "durability-unproven",
        "ephemeral-or-tracking",
    ]
    assert all(link["normalized_candidate_url"] is None for link in links)
    assert all(link["approval_status"] == "rejected" for link in links)


def test_approval_rejects_unknown_ids_and_leaves_unselected_candidate_pending(
    tmp_path: Path,
) -> None:
    source = _pdf(
        tmp_path / "candidate.pdf",
        ("https://law.example/opinions/candidate.pdf",),
    )
    extraction = cast(
        dict[str, object],
        _api("extract_pdf_link_annotations")(source, authority_id="auth-candidate"),
    )
    with pytest.raises(AuthorityPackageError, match="undeclared candidate"):
        _api("dispose_pdf_link_annotations")(
            extraction,
            approved_link_ids={"link-not-declared"},
            source_identity_verified=True,
        )

    disposition = cast(
        dict[str, object],
        _api("dispose_pdf_link_annotations")(
            extraction,
            approved_link_ids=set(),
            source_identity_verified=True,
        ),
    )
    link = cast(list[dict[str, Any]], disposition["links"])[0]
    assert disposition["approved_link_count"] == 0
    assert link["approval_status"] == "pending"
    assert link["final_inserted_url"] is None


def test_encrypted_unreadable_and_symlinked_pdfs_are_rejected(tmp_path: Path) -> None:
    encrypted = _pdf(tmp_path / "encrypted.pdf", password="secret")
    with pytest.raises(AuthorityPackageError, match="encrypted"):
        _api("extract_pdf_link_annotations")(encrypted, authority_id="auth-encrypted")

    unreadable = tmp_path / "unreadable.pdf"
    unreadable.write_bytes(b"not a pdf")
    with pytest.raises(AuthorityPackageError, match="readable PDF"):
        _api("extract_pdf_link_annotations")(unreadable, authority_id="auth-unreadable")

    target = _pdf(tmp_path / "target.pdf")
    symlink = tmp_path / "symlink.pdf"
    symlink.symlink_to(target)
    with pytest.raises(AuthorityPackageError, match="readable PDF"):
        _api("extract_pdf_link_annotations")(symlink, authority_id="auth-symlink")


def test_disposition_rejects_unsupported_extraction_schema() -> None:
    with pytest.raises(AuthorityPackageError, match="unsupported schema"):
        _api("dispose_pdf_link_annotations")(
            {"schema_version": 2, "links": []},
            approved_link_ids=set(),
            source_identity_verified=True,
        )


def test_private_link_disposition_manifest_is_written_once(tmp_path: Path) -> None:
    payload = {
        "schema_version": 1,
        "authority_id": "auth-manifest",
        "source_pdf_sha256": "1" * 64,
        "source_identity_verified": True,
        "malformed_annotation_count": 0,
        "approved_link_count": 0,
        "links": [],
    }
    output = tmp_path / "private-link-disposition.json"
    written = _api("write_pdf_link_disposition_manifest")(payload, output)

    assert written == output
    assert json.loads(output.read_text(encoding="utf-8")) == payload
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    with pytest.raises(AuthorityPackageError, match="already exists"):
        _api("write_pdf_link_disposition_manifest")(payload, output)
