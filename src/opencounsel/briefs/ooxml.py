from __future__ import annotations

import os
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from lxml import etree

from opencounsel.briefs.docx import NS, BriefDocxError

XML_SPACE = "{http://www.w3.org/XML/1998/namespace}space"


@dataclass(frozen=True, slots=True)
class TextNodeSpan:
    node: etree._Element | None
    start: int
    end: int


def parse_word_xml(
    data: bytes,
    error_type: type[BriefDocxError] = BriefDocxError,
) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise error_type("OOXML part contains invalid XML") from exc


def part_members(
    part: str,
    error_type: type[BriefDocxError] = BriefDocxError,
) -> tuple[str, str]:
    if part == "document":
        return "word/document.xml", "word/_rels/document.xml.rels"
    if part.startswith("footnote:"):
        return "word/footnotes.xml", "word/_rels/footnotes.xml.rels"
    if part.startswith("endnote:"):
        return "word/endnotes.xml", "word/_rels/endnotes.xml.rels"
    raise error_type(f"unsupported Word part: {part}")


def paragraphs_for_part(
    root: etree._Element,
    part: str,
    error_type: type[BriefDocxError] = BriefDocxError,
) -> list[etree._Element]:
    if part == "document":
        return cast(
            list[etree._Element], root.xpath(".//w:body//w:p", namespaces=NS)
        )
    if ":" not in part:
        raise error_type(f"unsupported Word part: {part}")
    prefix, raw_id = part.split(":", maxsplit=1)
    if prefix not in {"footnote", "endnote"}:
        raise error_type(f"unsupported Word part: {part}")
    container_name = "footnote" if prefix == "footnote" else "endnote"
    containers = cast(
        list[etree._Element],
        root.xpath(
            f"./w:{container_name}[@w:id=$note_id]", namespaces=NS, note_id=raw_id
        ),
    )
    if not containers:
        return []
    return cast(list[etree._Element], containers[0].xpath(".//w:p", namespaces=NS))


def visible_text(element: etree._Element) -> str:
    chunks: list[str] = []

    def walk(node: etree._Element) -> None:
        tag = etree.QName(node).localname
        if tag in {"del", "moveFrom"}:
            return
        if tag == "t" and node.text:
            chunks.append(node.text)
            return
        if tag == "tab":
            chunks.append("\t")
            return
        if tag in {"br", "cr"}:
            chunks.append("\n")
            return
        for child in node:
            walk(child)

    walk(element)
    return "".join(chunks)


def visible_text_spans(element: etree._Element) -> tuple[TextNodeSpan, ...]:
    spans: list[TextNodeSpan] = []
    cursor = 0

    def walk(node: etree._Element) -> None:
        nonlocal cursor
        tag = etree.QName(node).localname
        if tag in {"del", "moveFrom"}:
            return
        if tag == "t" and node.text:
            end = cursor + len(node.text)
            spans.append(TextNodeSpan(node, cursor, end))
            cursor = end
            return
        if tag in {"tab", "br", "cr"}:
            spans.append(TextNodeSpan(None, cursor, cursor + 1))
            cursor += 1
            return
        for child in node:
            walk(child)

    walk(element)
    return tuple(spans)


def write_docx_package(
    archive: zipfile.ZipFile,
    output: Path,
    modified: dict[str, bytes],
    added: dict[str, bytes] | None = None,
) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".docx", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w") as outgoing:
            for member in archive.infolist():
                outgoing.writestr(member, modified.get(member.filename, archive.read(member)))
            for name, data in (added or {}).items():
                outgoing.writestr(name, data, compress_type=zipfile.ZIP_DEFLATED)
        temporary.chmod(0o600)
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def update_xml_space(node: etree._Element) -> None:
    text = node.text or ""
    if text[:1].isspace() or text[-1:].isspace():
        node.set(XML_SPACE, "preserve")
    elif XML_SPACE in node.attrib:
        del node.attrib[XML_SPACE]
