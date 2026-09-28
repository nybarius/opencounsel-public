from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import zipfile
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from lxml import etree
from pydantic import Field
from pypdf import PdfReader

from opencounsel.briefs.docx import (
    NS,
    R_NS,
    W_NS,
    BriefDocxError,
    inspect_brief_docx,
)
from opencounsel.briefs.ooxml import (
    paragraphs_for_part,
    parse_word_xml,
    part_members,
    visible_text,
    write_docx_package,
)
from opencounsel.contracts.models import (
    ContractModel,
    FrontMatterSource,
    ToaSourceEntry,
    TocSourceEntry,
)
from opencounsel.contracts.schema import validate_contract
from opencounsel.revisions import RevisionStore

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
TOA_SOFT_BREAK_THRESHOLD = 70
type Runner = Callable[..., subprocess.CompletedProcess[str]]


class FossPublicationError(BriefDocxError):
    """Raised when explicit front matter or FOSS rendering fails closed."""


class FossPublicationManifest(ContractModel):
    schema_version: Literal[1] = 1
    process_id: str = Field(pattern=r"^proc-[0-9a-f]{64}$")
    engine: Literal["libreoffice"] = "libreoffice"
    engine_version: str = Field(min_length=1, max_length=256)
    input_docx_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_docx_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_pdf_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    page_count: int = Field(ge=1)
    toc_entry_count: int = Field(ge=0)
    toa_authority_count: int = Field(ge=0)
    toa_occurrence_count: int = Field(ge=0)
    created_at: str


def publish_foss(
    store: RevisionStore,
    process_id: str,
    *,
    executable: str = "libreoffice",
    runner: Runner = subprocess.run,
) -> FossPublicationManifest:
    """Compile explicit PAGEREF front matter and render a PDF with LibreOffice."""
    process = store.load_process(process_id)
    corrected, _ledger = store.delivery_paths(process_id)
    front_matter = store.load_front_matter_source(process_id)
    delivery = corrected.parent
    published = delivery / "published.docx"
    pdf = delivery / "published.pdf"
    manifest_path = delivery / "publication.json"
    existing = [path.exists() or path.is_symlink() for path in (published, pdf, manifest_path)]
    if any(existing):
        if not all(existing):
            raise FossPublicationError("publication output set is incomplete")
        return load_foss_publication(store, process_id)

    _compile_pageref_front_matter(corrected, published, front_matter)
    engine_version = _engine_version(executable, runner)
    page_count = _render_pdf(published, pdf, executable, runner)
    if front_matter.toc:
        toc_pages = _resolve_toc_pages(pdf, list(front_matter.toc))
        _rewrite_static_toc(published, list(front_matter.toc), toc_pages)
    cross_part_authorities = [
        authority
        for authority in front_matter.toa
        if any(location.part != "document" for location in authority.locations)
    ]
    document_authorities = [
        authority
        for authority in front_matter.toa
        if all(location.part == "document" for location in authority.locations)
    ]
    if front_matter.toa:
        occurrence_pages = _resolve_toa_occurrence_pages(pdf, document_authorities)
        occurrence_pages.update(
            _resolve_source_occurrence_pages(pdf, cross_part_authorities)
        )
        _rewrite_deduplicated_toa(
            published, list(front_matter.toa), occurrence_pages
        )
    if front_matter.toc or front_matter.toa:
        _validate_static_front_matter(published, front_matter)
        page_count = _render_pdf(published, pdf, executable, runner)
    manifest = FossPublicationManifest(
        process_id=process_id,
        engine_version=engine_version,
        input_docx_sha256=process.corrected_sha256,
        output_docx_sha256=_hash_path(published),
        output_pdf_sha256=_hash_path(pdf),
        page_count=page_count,
        toc_entry_count=len(front_matter.toc),
        toa_authority_count=len(front_matter.toa),
        toa_occurrence_count=sum(len(item.locations) for item in front_matter.toa),
        created_at=datetime.now(UTC).isoformat(),
    )
    payload = manifest.model_dump(mode="json")
    validate_contract("publication-manifest.schema.json", payload)
    _write_json_once(manifest_path, payload)
    return manifest


def load_foss_publication(
    store: RevisionStore,
    process_id: str,
) -> FossPublicationManifest:
    """Load and verify one immutable FOSS publication packet."""
    process = store.load_process(process_id)
    delivery = store.deliveries / process_id
    published = delivery / "published.docx"
    pdf = delivery / "published.pdf"
    manifest_path = delivery / "publication.json"
    for path in (published, pdf, manifest_path):
        if path.is_symlink() or not path.is_file():
            raise FossPublicationError("publication artifact is missing or unsafe")
    if manifest_path.stat().st_size > 64 * 1024:
        raise FossPublicationError("publication manifest exceeds size limit")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise FossPublicationError("publication manifest must be a JSON object")
        validate_contract("publication-manifest.schema.json", payload)
        manifest = FossPublicationManifest.model_validate(payload)
    except FossPublicationError:
        raise
    except Exception as exc:
        raise FossPublicationError("publication manifest is invalid") from exc
    try:
        page_count = len(PdfReader(pdf).pages)
    except Exception as exc:
        raise FossPublicationError("published PDF is invalid") from exc
    if (
        manifest.process_id != process_id
        or manifest.input_docx_sha256 != process.corrected_sha256
        or manifest.output_docx_sha256 != _hash_path(published)
        or manifest.output_pdf_sha256 != _hash_path(pdf)
        or manifest.page_count != page_count
    ):
        raise FossPublicationError("publication packet does not match its manifest")
    inspect_brief_docx(published)
    return manifest


def render_docx_reference_pdf(
    source: Path,
    output: Path,
    *,
    executable: str = "libreoffice",
    runner: Runner = subprocess.run,
) -> int:
    """Render an immutable DOCX as a separate PDF review artifact."""
    if source.resolve() == output.resolve():
        raise FossPublicationError("reference render must write a separate PDF")
    if output.exists() or output.is_symlink():
        raise FossPublicationError("reference render output already exists")
    if not output.parent.is_dir():
        raise FossPublicationError("reference render output directory is missing")
    inspect_brief_docx(source)
    source_sha256 = _hash_path(source)
    page_count = _render_pdf(source, output, executable, runner)
    if _hash_path(source) != source_sha256:
        output.unlink(missing_ok=True)
        raise FossPublicationError("reference render changed its source DOCX")
    return page_count


def _compile_pageref_front_matter(
    source: Path,
    output: Path,
    front_matter: FrontMatterSource,
) -> None:
    inspection = inspect_brief_docx(source)
    if source.resolve() == output.resolve():
        raise FossPublicationError("publication must write a new DOCX")
    if output.exists() or output.is_symlink():
        raise FossPublicationError("publication DOCX already exists")
    slots = [
        paragraph.text
        for paragraph in inspection.paragraphs
        if paragraph.part == "document" and paragraph.text in {"[TOC]", "[TOA]"}
    ]
    if slots.count("[TOC]") != 1 or slots.count("[TOA]") != 1:
        raise FossPublicationError("publication requires exactly one TOC and TOA slot")

    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)
    with zipfile.ZipFile(source) as archive:
        document_root = parse_word_xml(
            archive.read("word/document.xml"), FossPublicationError
        )
        roots: dict[str, etree._Element] = {"document": document_root}
        member_roots: dict[str, etree._Element] = {
            "word/document.xml": document_root
        }
        for part in {
            location.part
            for authority in front_matter.toa
            for location in authority.locations
            if location.part != "document"
        }:
            xml_name, _rels_name = part_members(part, FossPublicationError)
            if xml_name in archive.namelist():
                root = member_roots.get(xml_name)
                if root is None:
                    root = parse_word_xml(
                        archive.read(xml_name), FossPublicationError
                    )
                    member_roots[xml_name] = root
                roots[part] = root
        style_ids = _style_ids(archive.read("word/styles.xml"))
        target_ids = _external_relationship_ids(
            archive.read("word/_rels/document.xml.rels")
        )
        next_bookmark_id = _next_bookmark_id(member_roots.values())
        toc_bookmarks: dict[str, str] = {}
        toa_bookmarks: dict[tuple[str, int], str] = {}

        for entry in front_matter.toc:
            paragraphs = paragraphs_for_part(document_root, entry.part, FossPublicationError)
            paragraph = _paragraph_at(paragraphs, entry.paragraph_index, "TOC target")
            if " ".join(visible_text(paragraph).split()) != entry.heading:
                raise FossPublicationError("TOC target text no longer matches its source")
            bookmark = _bookmark_name("toc", entry.entry_id)
            next_bookmark_id = _add_bookmark(
                paragraph, bookmark, next_bookmark_id
            )
            toc_bookmarks[entry.entry_id] = bookmark

        for authority in front_matter.toa:
            for location_index, location in enumerate(authority.locations):
                root = roots.get(location.part)
                if root is None:
                    raise FossPublicationError("TOA target Word part is missing")
                paragraphs = paragraphs_for_part(root, location.part, FossPublicationError)
                paragraph = _paragraph_at(
                    paragraphs, location.paragraph_index, "TOA target"
                )
                text = visible_text(paragraph)
                if text[location.start_offset : location.end_offset] != location.original_text:
                    raise FossPublicationError("TOA target text no longer matches its source")
                bookmark = _bookmark_name(
                    "toa", f"{authority.authority_id}-{location_index}"
                )
                next_bookmark_id = _add_bookmark(
                    paragraph, bookmark, next_bookmark_id
                )
                toa_bookmarks[(authority.authority_id, location_index)] = bookmark

        document_paragraphs = paragraphs_for_part(
            document_root, "document", FossPublicationError
        )
        toc_slot = _single_slot(document_paragraphs, "[TOC]")
        toa_slot = _single_slot(document_paragraphs, "[TOA]")
        toc_paragraphs = [
            _toc_entry_paragraph(
                entry.heading,
                entry.level,
                entry.number_label,
                toc_bookmarks[entry.entry_id],
                style_ids,
            )
            for entry in front_matter.toc
        ]
        toa_paragraphs: list[etree._Element] = []
        category: str | None = None
        for authority in front_matter.toa:
            if authority.category_heading != category:
                category = authority.category_heading
                toa_paragraphs.append(
                    _text_paragraph(
                        category,
                        style_ids.get("_LegalTOACategory", "LegalTOACategory"),
                    )
                )
            bookmarks = [
                toa_bookmarks[(authority.authority_id, index)]
                for index in range(len(authority.locations))
            ]
            target = authority.existing_targets[0] if len(authority.existing_targets) == 1 else None
            toa_paragraphs.append(
                _toa_entry_paragraph(
                    authority.display_name,
                    authority.italic_spans,
                    bookmarks,
                    style_ids,
                    relationship_id=target_ids.get(target) if target else None,
                )
            )
        _replace_paragraph(toc_slot, toc_paragraphs or [_text_paragraph("None", None)])
        _replace_paragraph(toa_slot, toa_paragraphs or [_text_paragraph("None", None)])

        modified = {
            xml_name: _serialize(root)
            for xml_name, root in member_roots.items()
        }
        temporary = write_docx_package(archive, output, modified)
    try:
        projected = inspect_brief_docx(temporary)
        if any(
            paragraph.text in {"[TOC]", "[TOA]"}
            for paragraph in projected.paragraphs
        ):
            raise FossPublicationError("publication placeholders remain in DOCX")
        os.replace(temporary, output)
        output.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _style_ids(styles_xml: bytes) -> dict[str, str]:
    root = parse_word_xml(styles_xml, FossPublicationError)
    values: dict[str, str] = {}
    for style in cast(list[etree._Element], root.xpath("./w:style", namespaces=NS)):
        names = cast(
            list[str], style.xpath("./w:name/@w:val", namespaces=NS)
        )
        style_id = style.get(f"{{{W_NS}}}styleId")
        if names and style_id:
            values[names[0]] = style_id
    return values


def _external_relationship_ids(relationships_xml: bytes) -> dict[str, str]:
    root = parse_word_xml(relationships_xml, FossPublicationError)
    return {
        target: relationship_id
        for relationship in root.findall(f"{{{REL_NS}}}Relationship")
        if relationship.get("TargetMode") == "External"
        and (target := relationship.get("Target")) is not None
        and (relationship_id := relationship.get("Id")) is not None
    }


def _next_bookmark_id(roots: Iterable[etree._Element]) -> int:
    values: list[int] = []
    for root in roots:
        for value in cast(
            list[str], root.xpath(".//w:bookmarkStart/@w:id", namespaces=NS)
        ):
            if value.isdigit():
                values.append(int(value))
    return max(values, default=0) + 1


def _bookmark_name(kind: str, identity: str) -> str:
    digest = hashlib.sha256(identity.encode()).hexdigest()[:24]
    return f"OC_{kind}_{digest}"


def _add_bookmark(paragraph: etree._Element, name: str, bookmark_id: int) -> int:
    start = etree.Element(f"{{{W_NS}}}bookmarkStart")
    start.set(f"{{{W_NS}}}id", str(bookmark_id))
    start.set(f"{{{W_NS}}}name", name)
    end = etree.Element(f"{{{W_NS}}}bookmarkEnd")
    end.set(f"{{{W_NS}}}id", str(bookmark_id))
    properties = paragraph.find(f"{{{W_NS}}}pPr")
    paragraph.insert(1 if properties is not None else 0, start)
    paragraph.append(end)
    return bookmark_id + 1


def _paragraph_at(
    paragraphs: list[etree._Element], index: int, label: str
) -> etree._Element:
    if index >= len(paragraphs):
        raise FossPublicationError(f"{label} paragraph is missing")
    return paragraphs[index]


def _single_slot(paragraphs: list[etree._Element], text: str) -> etree._Element:
    matches = [paragraph for paragraph in paragraphs if visible_text(paragraph) == text]
    if len(matches) != 1:
        raise FossPublicationError(f"publication requires exactly one {text} slot")
    return matches[0]


def _toc_entry_paragraph(
    text: str,
    level: int,
    number_label: str | None,
    bookmark: str,
    style_ids: dict[str, str],
) -> etree._Element:
    paragraph = _paragraph(style_ids.get(f"TOC {min(level, 9)}", f"TOC{min(level, 9)}"))
    paragraph.append(_toc_heading_hyperlink(text, number_label, bookmark))
    paragraph.append(_tab_run())
    paragraph.extend(_pageref_runs(bookmark))
    return paragraph


def _toc_static_entry_paragraph(
    text: str,
    level: int,
    number_label: str | None,
    bookmark: str,
    page_label: str,
    style_ids: dict[str, str],
) -> etree._Element:
    paragraph = _paragraph(
        style_ids.get(f"TOC {min(level, 9)}", f"TOC{min(level, 9)}")
    )
    paragraph.append(_toc_heading_hyperlink(text, number_label, bookmark))
    paragraph.append(_tab_run())
    paragraph.append(_internal_hyperlink(page_label, bookmark))
    return paragraph


def _toc_heading_hyperlink(
    text: str,
    number_label: str | None,
    bookmark: str,
) -> etree._Element:
    hyperlink = etree.Element(f"{{{W_NS}}}hyperlink")
    hyperlink.set(f"{{{W_NS}}}anchor", bookmark)
    hyperlink.set(f"{{{W_NS}}}history", "1")
    if number_label is not None:
        hyperlink.append(_text_run(number_label))
        hyperlink.append(_tab_run())
    hyperlink.append(_text_run(text))
    return hyperlink


def _toa_entry_paragraph(
    text: str,
    italic_spans: tuple[tuple[int, int], ...],
    bookmarks: list[str],
    style_ids: dict[str, str],
    *,
    relationship_id: str | None,
) -> etree._Element:
    paragraph = _paragraph(
        style_ids.get("Table of Authorities", "TableofAuthorities")
    )
    container: etree._Element = paragraph
    if relationship_id is not None:
        hyperlink = etree.SubElement(paragraph, f"{{{W_NS}}}hyperlink")
        hyperlink.set(f"{{{R_NS}}}id", relationship_id)
        hyperlink.set(f"{{{W_NS}}}history", "1")
        container = hyperlink
    _append_toa_text(container, text, italic_spans)
    paragraph.append(_tab_run())
    for index, bookmark in enumerate(bookmarks):
        if index:
            paragraph.append(_text_run(", "))
        paragraph.extend(_pageref_runs(bookmark))
    return paragraph


def _styled_chunks(
    text: str, spans: tuple[tuple[int, int], ...]
) -> list[tuple[str, bool]]:
    chunks: list[tuple[str, bool]] = []
    cursor = 0
    for start, end in spans:
        if cursor < start:
            chunks.append((text[cursor:start], False))
        chunks.append((text[start:end], True))
        cursor = end
    if cursor < len(text):
        chunks.append((text[cursor:], False))
    return chunks or [(text, False)]


def _append_toa_text(
    container: etree._Element,
    text: str,
    italic_spans: tuple[tuple[int, int], ...],
) -> None:
    break_at = _toa_soft_break_position(text, italic_spans)
    cursor = 0
    inserted = False
    for chunk, italic in _styled_chunks(text, italic_spans):
        end = cursor + len(chunk)
        if not inserted and break_at is not None and cursor <= break_at <= end:
            local = break_at - cursor
            if before := chunk[:local]:
                container.append(_text_run(before, italic=italic))
            container.append(_line_break_run())
            if after := chunk[local:]:
                container.append(_text_run(after, italic=italic))
            inserted = True
        else:
            container.append(_text_run(chunk, italic=italic))
        cursor = end


def _toa_soft_break_position(
    text: str,
    italic_spans: tuple[tuple[int, int], ...],
) -> int | None:
    if len(text) < TOA_SOFT_BREAK_THRESHOLD or not italic_spans:
        return None
    comma = text.find(",", max(end for _, end in italic_spans))
    if comma < 0:
        return None
    position = comma + 1
    while position < len(text) and text[position] == " ":
        position += 1
    return position if position < len(text) else None


def _text_paragraph(text: str, style_id: str | None) -> etree._Element:
    paragraph = _paragraph(style_id)
    paragraph.append(_text_run(text))
    return paragraph


def _paragraph(style_id: str | None) -> etree._Element:
    paragraph = etree.Element(f"{{{W_NS}}}p")
    if style_id:
        properties = etree.SubElement(paragraph, f"{{{W_NS}}}pPr")
        style = etree.SubElement(properties, f"{{{W_NS}}}pStyle")
        style.set(f"{{{W_NS}}}val", style_id)
    return paragraph


def _internal_hyperlink(text: str, bookmark: str) -> etree._Element:
    hyperlink = etree.Element(f"{{{W_NS}}}hyperlink")
    hyperlink.set(f"{{{W_NS}}}anchor", bookmark)
    hyperlink.set(f"{{{W_NS}}}history", "1")
    hyperlink.append(_text_run(text))
    return hyperlink


def _pageref_runs(bookmark: str) -> list[etree._Element]:
    return [
        _field_char_run("begin", dirty=True),
        _instruction_run(f" PAGEREF {bookmark} \\h "),
        _field_char_run("separate"),
        _text_run("0"),
        _field_char_run("end"),
    ]


def _field_char_run(kind: str, *, dirty: bool = False) -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    field = etree.SubElement(run, f"{{{W_NS}}}fldChar")
    field.set(f"{{{W_NS}}}fldCharType", kind)
    if dirty:
        field.set(f"{{{W_NS}}}dirty", "true")
    return run


def _instruction_run(text: str) -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    instruction = etree.SubElement(run, f"{{{W_NS}}}instrText")
    instruction.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    instruction.text = text
    return run


def _tab_run() -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    etree.SubElement(run, f"{{{W_NS}}}tab")
    return run


def _line_break_run() -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    etree.SubElement(run, f"{{{W_NS}}}br")
    return run


def _text_run(text: str, *, italic: bool = False) -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    if italic:
        properties = etree.SubElement(run, f"{{{W_NS}}}rPr")
        etree.SubElement(properties, f"{{{W_NS}}}i")
        etree.SubElement(properties, f"{{{W_NS}}}iCs")
    value = etree.SubElement(run, f"{{{W_NS}}}t")
    value.text = text
    if text[:1].isspace() or text[-1:].isspace():
        value.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    return run


def _replace_paragraph(
    paragraph: etree._Element, replacements: list[etree._Element]
) -> None:
    parent = paragraph.getparent()
    if parent is None:
        raise FossPublicationError("front-matter slot has no parent")
    if not replacements:
        raise FossPublicationError("front-matter slot requires a replacement")

    # Word stores a section break on the paragraph immediately before the new
    # section. Normalization deliberately puts the front/body break on the TOA
    # slot, so replacing that paragraph must transfer its sectPr to the last
    # generated TOA paragraph. Dropping it collapses Roman and Arabic pagination.
    paragraph_properties = paragraph.find(f"{{{W_NS}}}pPr")
    section_properties = (
        paragraph_properties.find(f"{{{W_NS}}}sectPr")
        if paragraph_properties is not None
        else None
    )
    if section_properties is not None and paragraph_properties is not None:
        paragraph_properties.remove(section_properties)
        replacement_properties = replacements[-1].find(f"{{{W_NS}}}pPr")
        if replacement_properties is None:
            replacement_properties = etree.Element(f"{{{W_NS}}}pPr")
            replacements[-1].insert(0, replacement_properties)
        replacement_properties.append(section_properties)

    index = parent.index(paragraph)
    parent.remove(paragraph)
    for offset, replacement in enumerate(replacements):
        parent.insert(index + offset, replacement)


def _resolve_toc_pages(
    pdf: Path,
    entries: list[TocSourceEntry],
) -> dict[str, str]:
    try:
        reader = PdfReader(pdf)
        page_texts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise FossPublicationError("cannot read first-pass TOC pages") from exc
    normalized_pages = [" ".join(text.split()) for text in page_texts]
    body_start = _body_start_page(page_texts)
    resolved: dict[str, str] = {}
    for entry in entries:
        candidates = [
            page_index
            for page_index in range(body_start, len(page_texts))
            if _page_contains_heading(page_texts[page_index], entry.heading)
        ]
        if len(candidates) != 1:
            raise FossPublicationError(
                "LibreOffice did not expose an unambiguous TOC heading page"
            )
        resolved[entry.entry_id] = _rendered_page_label(
            normalized_pages, candidates[0], body_start
        )
    return resolved


def _page_contains_heading(page_text: str, heading: str) -> bool:
    expected = " ".join(heading.split()).casefold()
    lines = [" ".join(line.split()) for line in page_text.splitlines()]
    lines = [line for line in lines if line]
    for start in range(len(lines)):
        first = re.sub(
            r"^(?:[IVXLCDM]+|[A-Z]|\d+|[a-z])\.\s+",
            "",
            lines[start],
        )
        combined = first
        for end in range(start, min(start + 4, len(lines))):
            if end > start:
                combined = f"{combined} {lines[end]}"
            normalized = " ".join(combined.split()).casefold()
            if normalized == expected:
                return True
            if not expected.startswith(f"{normalized} "):
                break
    return False


def _rewrite_static_toc(
    path: Path,
    entries: list[TocSourceEntry],
    page_labels: dict[str, str],
) -> None:
    with zipfile.ZipFile(path) as archive:
        root = parse_word_xml(archive.read("word/document.xml"), FossPublicationError)
        style_ids = _style_ids(archive.read("word/styles.xml"))
        paragraphs = paragraphs_for_part(root, "document", FossPublicationError)
        for entry in entries:
            bookmark = _bookmark_name("toc", entry.entry_id)
            candidates = [
                paragraph
                for paragraph in paragraphs
                if bookmark
                in "".join(
                    cast(
                        list[str],
                        paragraph.xpath(".//w:instrText/text()", namespaces=NS),
                    )
                )
            ]
            if len(candidates) != 1:
                raise FossPublicationError("generated TOC entry cannot be identified")
            replacement = _toc_static_entry_paragraph(
                entry.heading,
                entry.level,
                entry.number_label,
                bookmark,
                page_labels[entry.entry_id],
                style_ids,
            )
            _replace_paragraph(candidates[0], [replacement])
        temporary = write_docx_package(
            archive,
            path,
            {"word/document.xml": _serialize(root)},
        )
    try:
        inspect_brief_docx(temporary)
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _validate_static_front_matter(
    path: Path,
    front_matter: FrontMatterSource,
) -> None:
    with zipfile.ZipFile(path) as archive:
        root = parse_word_xml(archive.read("word/document.xml"), FossPublicationError)
        style_ids = _style_ids(archive.read("word/styles.xml"))
    instructions = " ".join(
        cast(list[str], root.xpath(".//w:instrText/text()", namespaces=NS))
    )
    if "PAGEREF" in instructions:
        raise FossPublicationError("terminal front matter still contains PAGEREF fields")
    toc_paragraphs = cast(
        list[etree._Element],
        root.xpath(
            ".//w:p[starts-with(w:pPr/w:pStyle/@w:val, 'TOC')]",
            namespaces=NS,
        ),
    )
    toc_count = len(toc_paragraphs)
    toa_style = style_ids.get("Table of Authorities", "TableofAuthorities")
    toa_paragraphs = cast(
        list[etree._Element],
        root.xpath(
            f'.//w:p[w:pPr/w:pStyle/@w:val="{toa_style}"]',
            namespaces=NS,
        ),
    )
    toa_count = len(toa_paragraphs)
    if toc_count != len(front_matter.toc) or toa_count != len(front_matter.toa):
        raise FossPublicationError("terminal front-matter entry counts are incomplete")


def _resolve_toa_occurrence_pages(
    pdf: Path,
    authorities: list[ToaSourceEntry],
) -> dict[str, tuple[str, ...]]:
    try:
        reader = PdfReader(pdf)
        extracted = " ".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        raise FossPublicationError("cannot read first-pass TOA page references") from exc
    text = " ".join(extracted.split())
    page_label = r"(?:\d+|[ivxlcdm]+)(?![A-Za-z0-9])"
    resolved: dict[str, tuple[str, ...]] = {}
    for authority in authorities:
        authority_id = authority.authority_id
        display_name = " ".join(authority.display_name.split())
        occurrence_count = len(authority.locations)
        escaped_name = re.escape(display_name).replace(r"\ ", r"\s+")
        pattern = re.compile(
            escaped_name
            + rf"(?:\s|\.)+(?P<pages>{page_label}"
            + rf"(?:\s*,\s*{page_label}){{{occurrence_count - 1}}})(?!\s*,)",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if len(matches) != 1:
            raise FossPublicationError(
                "LibreOffice did not expose an unambiguous TOA page-reference sequence"
            )
        labels = tuple(
            label.strip() for label in matches[0].group("pages").split(",")
        )
        if len(labels) != occurrence_count:
            raise FossPublicationError("TOA page-reference count does not match its source")
        resolved[authority_id] = labels
    return resolved


def _resolve_source_occurrence_pages(
    pdf: Path,
    authorities: list[ToaSourceEntry],
) -> dict[str, tuple[str, ...]]:
    """Resolve citations in notes from body-page text instead of cross-part PAGEREFs.

    Word bookmarks live in individual OOXML parts. LibreOffice cannot evaluate a
    PAGEREF in the main document against a bookmark in footnotes or endnotes, so
    those fields render as broken references. The first-pass PDF remains a useful
    layout oracle: it contains the cited source text on the rendered note page.
    """
    if not authorities:
        return {}
    try:
        reader = PdfReader(pdf)
        page_texts = [page.extract_text() or "" for page in reader.pages]
    except Exception as exc:
        raise FossPublicationError("cannot read first-pass source pages") from exc
    if not page_texts:
        raise FossPublicationError("first-pass publication has no pages")

    body_start = _body_start_page(page_texts)
    normalized_pages = [" ".join(text.split()) for text in page_texts]
    searchable = [text.casefold() for text in normalized_pages]
    resolved: dict[str, tuple[str, ...]] = {}
    for authority in authorities:
        labels: list[str] = []
        used_occurrences: dict[str, int] = {}
        for location in authority.locations:
            needle = " ".join(location.original_text.split()).casefold()
            if not needle:
                raise FossPublicationError("TOA source occurrence is empty")
            candidates: list[int] = []
            for page_index in range(body_start, len(searchable)):
                candidates.extend([page_index] * searchable[page_index].count(needle))
            ordinal = used_occurrences.get(needle, 0)
            if ordinal >= len(candidates):
                raise FossPublicationError(
                    "LibreOffice did not expose a TOA source occurrence on a body page"
                )
            page_index = candidates[ordinal]
            used_occurrences[needle] = ordinal + 1
            labels.append(
                _rendered_page_label(normalized_pages, page_index, body_start)
            )
        resolved[authority.authority_id] = tuple(labels)
    return resolved


def _body_start_page(page_texts: list[str]) -> int:
    """Return the first non-Roman page after the initial front-matter run."""
    body_start = 0
    for page_index, text in enumerate(page_texts):
        lines = [" ".join(line.split()) for line in text.splitlines()]
        lines = [line for line in lines if line]
        if not lines:
            break
        edge_has_label = any(
            re.fullmatch(r"\(?[ivxlcdm]+\)?\.?", line, re.IGNORECASE)
            for line in (lines[0], lines[-1])
        )
        leading = lines[0].split(maxsplit=1)[0]
        inline_lower_label = leading.islower() and bool(
            re.fullmatch(r"[ivxlcdm]+", leading)
        )
        if edge_has_label or inline_lower_label:
            body_start = page_index + 1
            continue
        break
    return body_start


def _rendered_page_label(
    page_texts: list[str], page_index: int, body_start: int
) -> str:
    text = page_texts[page_index]
    first = text.split(maxsplit=1)[0].rstrip(".()") if text else ""
    if first.isdigit():
        return first
    return str(page_index - body_start + 1)


def _rewrite_deduplicated_toa(
    path: Path,
    authorities: list[ToaSourceEntry],
    occurrence_pages: dict[str, tuple[str, ...]],
) -> None:
    with zipfile.ZipFile(path) as archive:
        root = parse_word_xml(archive.read("word/document.xml"), FossPublicationError)
        style_ids = _style_ids(archive.read("word/styles.xml"))
        target_ids = _external_relationship_ids(
            archive.read("word/_rels/document.xml.rels")
        )
        paragraphs = paragraphs_for_part(root, "document", FossPublicationError)
        for authority in authorities:
            authority_id = authority.authority_id
            bookmarks = [
                _bookmark_name("toa", f"{authority_id}-{index}")
                for index in range(len(authority.locations))
            ]
            candidates = [
                paragraph
                for paragraph in paragraphs
                if all(
                    bookmark
                    in "".join(
                        cast(
                            list[str],
                            paragraph.xpath(".//w:instrText/text()", namespaces=NS),
                        )
                    )
                    for bookmark in bookmarks
                )
            ]
            if len(candidates) != 1:
                raise FossPublicationError("generated TOA entry cannot be identified")
            labels = occurrence_pages[authority_id]
            unique_targets: list[tuple[str, str | None]] = []
            target_indexes: dict[str, int] = {}
            for label, bookmark, location in zip(
                labels, bookmarks, authority.locations, strict=True
            ):
                target_bookmark = bookmark if location.part == "document" else None
                existing_index = target_indexes.get(label)
                if existing_index is None:
                    target_indexes[label] = len(unique_targets)
                    unique_targets.append((label, target_bookmark))
                elif (
                    unique_targets[existing_index][1] is None
                    and target_bookmark is not None
                ):
                    unique_targets[existing_index] = (label, target_bookmark)
            target = (
                authority.existing_targets[0]
                if len(authority.existing_targets) == 1
                else None
            )
            replacement = _toa_static_entry_paragraph(
                authority.display_name,
                authority.italic_spans,
                unique_targets,
                style_ids,
                relationship_id=target_ids.get(target) if target else None,
            )
            _replace_paragraph(candidates[0], [replacement])

        temporary = write_docx_package(
            archive,
            path,
            {"word/document.xml": _serialize(root)},
        )
    try:
        inspect_brief_docx(temporary)
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _toa_static_entry_paragraph(
    text: str,
    italic_spans: tuple[tuple[int, int], ...],
    page_targets: list[tuple[str, str | None]],
    style_ids: dict[str, str],
    *,
    relationship_id: str | None,
) -> etree._Element:
    paragraph = _paragraph(
        style_ids.get("Table of Authorities", "TableofAuthorities")
    )
    container: etree._Element = paragraph
    if relationship_id is not None:
        hyperlink = etree.SubElement(paragraph, f"{{{W_NS}}}hyperlink")
        hyperlink.set(f"{{{R_NS}}}id", relationship_id)
        hyperlink.set(f"{{{W_NS}}}history", "1")
        container = hyperlink
    _append_toa_text(container, text, italic_spans)
    paragraph.append(_tab_run())
    for index, (label, bookmark) in enumerate(page_targets):
        if index:
            paragraph.append(_text_run(", "))
        if bookmark is None:
            paragraph.append(_text_run(label))
        else:
            paragraph.append(_internal_hyperlink(label, bookmark))
    return paragraph


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        standalone=True,
    )


def _engine_version(executable: str, runner: Runner) -> str:
    result = runner(
        [executable, "--version"],
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    version = result.stdout.strip().splitlines()[0] if result.returncode == 0 else ""
    if not version:
        raise FossPublicationError("LibreOffice version check failed")
    return version[:256]


def _render_pdf(
    source: Path,
    output: Path,
    executable: str,
    runner: Runner,
) -> int:
    with tempfile.TemporaryDirectory(prefix="foss-render-", dir=output.parent) as temporary:
        root = Path(temporary)
        profile = root / "profile"
        converted = root / f"{source.stem}.pdf"
        result = runner(
            [
                executable,
                "--headless",
                "--nologo",
                "--nodefault",
                "--norestore",
                f"-env:UserInstallation={profile.resolve().as_uri()}",
                "--convert-to",
                "pdf:writer_pdf_Export",
                "--outdir",
                str(root),
                str(source),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0 or not converted.is_file():
            raise FossPublicationError("LibreOffice PDF render failed")
        try:
            reader = PdfReader(converted)
            if reader.is_encrypted or not reader.pages:
                raise FossPublicationError("rendered PDF is encrypted or empty")
            page_count = len(reader.pages)
        except FossPublicationError:
            raise
        except Exception as exc:
            raise FossPublicationError("rendered PDF is invalid") from exc
        os.replace(converted, output)
        output.chmod(0o600)
        return page_count


def _write_json_once(path: Path, payload: dict[str, object]) -> None:
    body = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    descriptor, temporary_name = tempfile.mkstemp(prefix="publication-", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        if fchmod := getattr(os, "fchmod", None):
            fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)
        path.chmod(0o600)
    except FileExistsError as exc:
        raise FossPublicationError("publication manifest already exists") from exc
    finally:
        temporary.unlink(missing_ok=True)


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "FossPublicationError",
    "FossPublicationManifest",
    "load_foss_publication",
    "publish_foss",
    "render_docx_reference_pdf",
]
