from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
    RectangleObject,
)

from opencounsel.source import authority_package


def _api(name: str) -> Callable[..., dict[str, object]]:
    function = getattr(authority_package, name, None)
    assert callable(function), f"{name} is not implemented"
    return cast(Callable[..., dict[str, object]], function)


def _linked_pdf(path: Path, links: list[tuple[str, tuple[float, float, float, float]]]) -> Path:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    for url, rectangle in links:
        writer.add_uri(0, url, RectangleObject(rectangle))
    with path.open("wb") as stream:
        writer.write(stream)
    return path


def test_durable_looking_annotation_requires_and_records_explicit_approval(
    tmp_path: Path,
) -> None:
    source = _linked_pdf(
        tmp_path / "opinion.pdf",
        [("https://law.example/opinions/smith-v-jones-2026.pdf", (72, 700, 240, 716))],
    )
    extraction = _api("extract_pdf_link_annotations")(
        source, authority_id="auth-1234567890abcdef"
    )

    assert extraction["source_pdf_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert extraction["malformed_annotation_count"] == 0
    link = cast(list[dict[str, Any]], extraction["links"])[0]
    assert link["authority_id"] == "auth-1234567890abcdef"
    assert link["page_number"] == 1
    assert link["annotation_rectangle"] == [72.0, 700.0, 240.0, 716.0]
    assert link["original_target_url"].endswith("smith-v-jones-2026.pdf")
    assert link["normalized_candidate_url"] == link["original_target_url"]
    assert link["classification"] == "durable-candidate"
    assert link["approval_status"] == "pending"
    assert link["final_inserted_url"] is None

    disposition = _api("dispose_pdf_link_annotations")(
        extraction,
        approved_link_ids={link["link_id"]},
        source_identity_verified=True,
    )
    approved = cast(list[dict[str, Any]], disposition["links"])[0]
    assert approved["approval_status"] == "approved"
    assert approved["final_inserted_url"] == approved["normalized_candidate_url"]
    assert approved["original_target_url"] == link["original_target_url"]
    assert approved["annotation_rectangle"] == link["annotation_rectangle"]


def test_search_session_and_tracking_links_are_ineligible_for_approval(
    tmp_path: Path,
) -> None:
    urls = [
        "https://law.example/search?q=smith+jones",
        "https://law.example/opinions/123?session=temporary",
        "https://law.example/opinions/123.pdf?utm_source=research",
    ]
    source = _linked_pdf(
        tmp_path / "ephemeral.pdf",
        [(url, (72, 700 - index * 24, 260, 716 - index * 24)) for index, url in enumerate(urls)],
    )
    extraction = _api("extract_pdf_link_annotations")(source, authority_id="auth-links")
    links = cast(list[dict[str, Any]], extraction["links"])

    assert [link["original_target_url"] for link in links] == urls
    assert all(link["classification"] == "ephemeral-or-tracking" for link in links)
    assert all(link["normalized_candidate_url"] is None for link in links)
    assert all(link["approval_status"] == "rejected" for link in links)
    assert all(link["abstention_reason"] for link in links)

    disposition = _api("dispose_pdf_link_annotations")(
        extraction,
        approved_link_ids={link["link_id"] for link in links},
        source_identity_verified=True,
    )
    disposed = cast(list[dict[str, Any]], disposition["links"])
    assert all(link["approval_status"] == "rejected" for link in disposed)
    assert all(link["final_inserted_url"] is None for link in disposed)


def test_identity_mismatch_prevents_durable_candidate_approval(tmp_path: Path) -> None:
    source = _linked_pdf(
        tmp_path / "identity-mismatch.pdf",
        [("https://law.example/documents/opinion-123.pdf", (10, 10, 100, 20))],
    )
    extraction = _api("extract_pdf_link_annotations")(source, authority_id="auth-mismatch")
    link = cast(list[dict[str, Any]], extraction["links"])[0]

    disposition = _api("dispose_pdf_link_annotations")(
        extraction,
        approved_link_ids={link["link_id"]},
        source_identity_verified=False,
    )
    rejected = cast(list[dict[str, Any]], disposition["links"])[0]
    assert rejected["approval_status"] == "rejected"
    assert rejected["final_inserted_url"] is None
    assert "identity" in rejected["abstention_reason"].lower()


def test_no_link_pdf_and_repeated_annotations_are_preserved(tmp_path: Path) -> None:
    no_links = _linked_pdf(tmp_path / "no-links.pdf", [])
    empty = _api("extract_pdf_link_annotations")(no_links, authority_id="auth-empty")
    assert empty["links"] == []
    assert empty["malformed_annotation_count"] == 0

    url = "https://law.example/opinions/repeated.pdf"
    repeated = _linked_pdf(
        tmp_path / "repeated.pdf",
        [(url, (10, 10, 100, 20)), (url, (10, 30, 100, 40))],
    )
    extraction = _api("extract_pdf_link_annotations")(repeated, authority_id="auth-repeat")
    links = cast(list[dict[str, Any]], extraction["links"])
    assert len(links) == 2
    assert len({link["link_id"] for link in links}) == 2
    assert [link["original_target_url"] for link in links] == [url, url]
    assert [link["annotation_rectangle"] for link in links] == [
        [10.0, 10.0, 100.0, 20.0],
        [10.0, 30.0, 100.0, 40.0],
    ]


def test_malformed_annotation_objects_are_counted_and_ignored(tmp_path: Path) -> None:
    source = tmp_path / "malformed-annots.pdf"
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    incomplete_link = DictionaryObject(
        {
            NameObject("/Subtype"): NameObject("/Link"),
            NameObject("/Rect"): RectangleObject((10, 10, 100, 20)),
        }
    )
    page[NameObject("/Annots")] = ArrayObject(
        [writer._add_object(incomplete_link), NumberObject(7)]
    )
    with source.open("wb") as stream:
        writer.write(stream)

    extraction = _api("extract_pdf_link_annotations")(source, authority_id="auth-malformed")
    assert extraction["links"] == []
    assert extraction["malformed_annotation_count"] == 2
