from __future__ import annotations

import hashlib
import re
import stat
import warnings
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import cast
from urllib.parse import urlparse

from lxml import etree

from opencounsel.briefs.ir import (
    BriefInspection,
    BriefParagraph,
    HeadingOccurrence,
    HyperlinkOccurrence,
)

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS = {"w": W_NS, "r": R_NS}

MAX_PACKAGE_BYTES = 50 * 1024 * 1024
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_TOTAL_BYTES = 200 * 1024 * 1024
MAX_MEMBERS = 5_000
MAX_COMPRESSION_RATIO = 200
ALLOWED_LINK_SCHEMES = {"http", "https", "mailto"}
HEADING_STYLE_LEVELS = {
    "Heading1": 1,
    "Heading2": 2,
    "Heading3": 3,
    "ArgumentSubheading": 3,
    "LegalHeadingBoldCtrUnderline": 1,
    "_LegalHeadingBoldCtrUnderline": 1,
    "LegalHeadingNum1": 2,
    "_LegalHeadingNum1": 2,
    "LegalHeadingNum2": 3,
    "_LegalHeadingNum2": 3,
    "LegalHeadingNum3": 4,
    "_LegalHeadingNum3": 4,
    "LegalHeadingNum4": 5,
    "_LegalHeadingNum4": 5,
}


class BriefDocxError(ValueError):
    """Raised when a brief cannot be inspected safely and deterministically."""


def inspect_brief_docx(path: Path) -> BriefInspection:
    if not path.is_file() or path.is_symlink() or path.suffix.lower() != ".docx":
        raise BriefDocxError("brief must be a regular DOCX file")
    size_bytes = path.stat().st_size
    if size_bytes > MAX_PACKAGE_BYTES:
        raise BriefDocxError("brief exceeds the 50 MiB package limit")

    digest = _hash_path(path)
    try:
        archive = zipfile.ZipFile(path)
    except (
        OSError,
        EOFError,
        UnicodeError,
        RuntimeError,
        NotImplementedError,
        zipfile.BadZipFile,
        zlib.error,
    ) as exc:
        raise BriefDocxError("brief is not a readable OOXML package") from exc

    with archive:
        try:
            names = _safe_members(archive)
            if "word/document.xml" not in names:
                raise BriefDocxError("OOXML package has no Word document body")
            paragraphs: list[BriefParagraph] = []
            paragraphs.extend(_read_part(archive, "word/document.xml", "document"))
            if "word/footnotes.xml" in names:
                paragraphs.extend(_read_footnotes(archive))
            if "word/endnotes.xml" in names:
                paragraphs.extend(_read_notes(archive, "endnotes", "endnote"))
        except (
            OSError,
            EOFError,
            UnicodeError,
            UserWarning,
            RuntimeError,
            NotImplementedError,
            zipfile.BadZipFile,
            zlib.error,
        ) as exc:
            raise BriefDocxError("OOXML package contains unreadable members") from exc

    headings = _infer_headings(paragraphs)
    return BriefInspection(digest, size_bytes, tuple(paragraphs), headings)


def _safe_members(archive: zipfile.ZipFile) -> set[str]:
    members = archive.infolist()
    if not members or len(members) > MAX_MEMBERS:
        raise BriefDocxError("OOXML package has an invalid member count")
    names: set[str] = set()
    total = 0
    for member in members:
        path = PurePosixPath(member.filename)
        if path.is_absolute() or ".." in path.parts or not path.name:
            raise BriefDocxError("OOXML package contains an unsafe member path")
        if member.filename in names:
            raise BriefDocxError("OOXML package contains duplicate member names")
        names.add(member.filename)
        mode = member.external_attr >> 16
        if stat.S_ISLNK(mode):
            raise BriefDocxError("OOXML package contains a symbolic link")
        if member.flag_bits & 0x1:
            raise BriefDocxError("encrypted OOXML members are not accepted")
        if member.file_size > MAX_MEMBER_BYTES:
            raise BriefDocxError("OOXML member exceeds the size limit")
        total += member.file_size
        if member.compress_size == 0 and member.file_size:
            raise BriefDocxError("OOXML member has an unsafe compression ratio")
        if member.compress_size and member.file_size / member.compress_size > MAX_COMPRESSION_RATIO:
            raise BriefDocxError("OOXML member has an unsafe compression ratio")
    if total > MAX_TOTAL_BYTES:
        raise BriefDocxError("OOXML package exceeds the expanded size limit")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        if archive.testzip() is not None:
            raise BriefDocxError("OOXML member failed its CRC check")
    return names


def _read_footnotes(archive: zipfile.ZipFile) -> list[BriefParagraph]:
    return _read_notes(archive, "footnotes", "footnote")


def _read_notes(
    archive: zipfile.ZipFile, collection: str, note_name: str
) -> list[BriefParagraph]:
    root = _parse_xml(archive.read(f"word/{collection}.xml"))
    relationships = _relationships(archive, f"word/_rels/{collection}.xml.rels")
    paragraphs: list[BriefParagraph] = []
    notes = cast(list[etree._Element], root.xpath(f"./w:{note_name}", namespaces=NS))
    for note in notes:
        raw_id = note.get(f"{{{W_NS}}}id", "")
        try:
            footnote_id = int(raw_id)
        except ValueError:
            continue
        if footnote_id < 0:
            continue
        elements = cast(list[etree._Element], note.xpath(".//w:p", namespaces=NS))
        for index, element in enumerate(elements):
            paragraphs.append(
                _read_paragraph(element, f"{note_name}:{footnote_id}", index, relationships)
            )
    return paragraphs


def _read_part(archive: zipfile.ZipFile, member_name: str, part: str) -> list[BriefParagraph]:
    root = _parse_xml(archive.read(member_name))
    relationship_name = "word/_rels/document.xml.rels"
    relationships = _relationships(archive, relationship_name)
    elements = cast(list[etree._Element], root.xpath(".//w:body//w:p", namespaces=NS))
    return [
        _read_paragraph(element, part, index, relationships)
        for index, element in enumerate(elements)
    ]


def _read_paragraph(
    element: etree._Element,
    part: str,
    index: int,
    relationships: dict[str, str],
) -> BriefParagraph:
    style = cast(list[str], element.xpath("./w:pPr/w:pStyle/@w:val", namespaces=NS))
    chunks: list[str] = []
    hyperlinks: list[HyperlinkOccurrence] = []

    def walk(node: etree._Element, relationship_id: str | None = None) -> None:
        tag = etree.QName(node).localname
        if tag in {"del", "moveFrom"}:
            return
        if tag == "hyperlink":
            relationship_id = node.get(f"{{{R_NS}}}id")
            start = sum(len(chunk) for chunk in chunks)
            for child in node:
                walk(child, relationship_id)
            end = sum(len(chunk) for chunk in chunks)
            target = relationships.get(relationship_id or "")
            if target and end > start:
                hyperlinks.append(
                    HyperlinkOccurrence("".join(chunks)[start:end], target, start, end)
                )
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
            walk(child, relationship_id)

    walk(element)
    return BriefParagraph(
        part=part,
        paragraph_index=index,
        style_id=style[0] if style else None,
        text="".join(chunks),
        hyperlinks=tuple(hyperlinks),
    )


def _relationships(archive: zipfile.ZipFile, member_name: str) -> dict[str, str]:
    try:
        data = archive.read(member_name)
    except KeyError:
        return {}
    root = _parse_xml(data)
    relationships: dict[str, str] = {}
    for relation in root:
        if relation.get("TargetMode") != "External":
            continue
        target = relation.get("Target", "")
        parsed = urlparse(target)
        if parsed.scheme.lower() not in ALLOWED_LINK_SCHEMES:
            continue
        relationship_id = relation.get("Id")
        if relationship_id:
            relationships[relationship_id] = target
    return relationships


def _infer_headings(paragraphs: list[BriefParagraph]) -> tuple[HeadingOccurrence, ...]:
    headings: list[HeadingOccurrence] = []
    for paragraph in paragraphs:
        if paragraph.part != "document":
            continue
        text = " ".join(paragraph.text.split())
        if not text:
            continue
        if paragraph.style_id in HEADING_STYLE_LEVELS:
            level = HEADING_STYLE_LEVELS[paragraph.style_id]
            basis = "paragraph-style"
        elif paragraph.style_id in {"_LegalCenter", "LegalCenter"} and _is_all_caps(text):
            level = 1
            basis = "centered-all-caps"
        else:
            continue
        headings.append(
            HeadingOccurrence(
                paragraph.part,
                paragraph.paragraph_index,
                text,
                paragraph.style_id,
                level,
                basis,
            )
        )
    return tuple(headings)


def _is_all_caps(text: str) -> bool:
    letters = re.sub(r"[^A-Za-z]", "", text)
    return bool(letters) and letters == letters.upper()


def _parse_xml(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
    try:
        return etree.fromstring(data, parser=parser)
    except etree.XMLSyntaxError as exc:
        raise BriefDocxError("OOXML part contains invalid XML") from exc


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
