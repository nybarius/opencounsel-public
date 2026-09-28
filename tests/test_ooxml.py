from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from opencounsel.briefs.docx import W_NS, BriefDocxError
from opencounsel.briefs.ooxml import (
    paragraphs_for_part,
    parse_word_xml,
    part_members,
    update_xml_space,
    visible_text,
    visible_text_spans,
    write_docx_package,
)


def test_shared_ooxml_part_and_paragraph_helpers() -> None:
    document = parse_word_xml(
        f"""
        <w:document xmlns:w="{W_NS}">
          <w:body><w:p><w:r><w:t>body</w:t></w:r></w:p></w:body>
        </w:document>
        """.encode()
    )
    notes = parse_word_xml(
        f"""
        <w:footnotes xmlns:w="{W_NS}">
          <w:footnote w:id="1"><w:p><w:r><w:t>note</w:t></w:r></w:p></w:footnote>
        </w:footnotes>
        """.encode()
    )

    assert visible_text(paragraphs_for_part(document, "document")[0]) == "body"
    assert visible_text(paragraphs_for_part(notes, "footnote:1")[0]) == "note"
    assert paragraphs_for_part(notes, "footnote:2") == []
    assert part_members("document")[0] == "word/document.xml"
    assert part_members("footnote:1")[0] == "word/footnotes.xml"
    assert part_members("endnote:1")[0] == "word/endnotes.xml"
    with pytest.raises(BriefDocxError, match="unsupported Word part"):
        part_members("header:1")
    with pytest.raises(BriefDocxError, match="unsupported Word part"):
        paragraphs_for_part(notes, "header")
    with pytest.raises(BriefDocxError, match="unsupported Word part"):
        paragraphs_for_part(notes, "header:1")
    with pytest.raises(BriefDocxError, match="invalid XML"):
        parse_word_xml(b"<unclosed>")


def test_shared_visible_text_spans_and_space_metadata() -> None:
    paragraph = parse_word_xml(
        f"""
        <w:p xmlns:w="{W_NS}">
          <w:del><w:r><w:t>deleted</w:t></w:r></w:del>
          <w:r><w:t xml:space="preserve"> left </w:t><w:tab/><w:br/></w:r>
        </w:p>
        """.encode()
    )

    assert visible_text(paragraph) == " left \t\n"
    spans = visible_text_spans(paragraph)
    assert [(span.start, span.end, span.node is None) for span in spans] == [
        (0, 6, False),
        (6, 7, True),
        (7, 8, True),
    ]
    node = spans[0].node
    assert node is not None
    node.text = "plain"
    update_xml_space(node)
    assert not node.attrib
    node.text = " trailing "
    update_xml_space(node)
    assert node.get("{http://www.w3.org/XML/1998/namespace}space") == "preserve"


def test_shared_package_writer_preserves_and_adds_members(tmp_path: Path) -> None:
    source = tmp_path / "source.zip"
    with zipfile.ZipFile(source, "w") as archive:
        archive.writestr("one.txt", "original")
        archive.writestr("two.txt", "preserved")
    output = tmp_path / "output.docx"
    with zipfile.ZipFile(source) as archive:
        temporary = write_docx_package(
            archive,
            output,
            {"one.txt": b"changed"},
            {"three.txt": b"added"},
        )

    with zipfile.ZipFile(temporary) as archive:
        assert archive.read("one.txt") == b"changed"
        assert archive.read("two.txt") == b"preserved"
        assert archive.read("three.txt") == b"added"
