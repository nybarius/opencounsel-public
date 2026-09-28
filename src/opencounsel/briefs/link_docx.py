from __future__ import annotations

import copy
import hashlib
import itertools
import json
import os
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path

from lxml import etree

from opencounsel.briefs.docx import R_NS, W_NS, BriefDocxError, inspect_brief_docx
from opencounsel.briefs.links import AuthorityLinkPlan, LinkInsertion, LinkReviewItem
from opencounsel.briefs.ooxml import (
    paragraphs_for_part,
    parse_word_xml,
    part_members,
    update_xml_space,
    visible_text,
    write_docx_package,
)

REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
HYPERLINK_REL = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink"
)
_TEXT_TAGS = {"t", "tab", "br", "cr"}


class LinkProjectionError(BriefDocxError):
    """Raised when a hyperlink projection would violate the Word safety contract."""


@dataclass(frozen=True, slots=True)
class LinkApplyResult:
    input_sha256: str
    plan_sha256: str
    output_sha256: str
    inserted_count: int
    review: tuple[LinkReviewItem, ...]
    inserted: tuple[LinkInsertion, ...] = ()


def apply_authority_links(
    source: Path,
    output: Path,
    plan: AuthorityLinkPlan,
) -> LinkApplyResult:
    """Apply safe plan entries to a new DOCX and prove visible text did not change."""
    inspection = inspect_brief_docx(source)
    if inspection.sha256 != plan.brief_sha256:
        raise LinkProjectionError("link plan does not match the input DOCX hash")
    if source.resolve() == output.resolve():
        raise LinkProjectionError("link projection must write a new DOCX")
    if output.exists() or output.is_symlink():
        raise LinkProjectionError("link projection output already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    by_part: dict[str, list[LinkInsertion]] = {}
    for insertion in plan.insertions:
        by_part.setdefault(insertion.part, []).append(insertion)
    _validate_nonoverlap(by_part)

    modified: dict[str, bytes] = {}
    added: dict[str, bytes] = {}
    review = list(plan.review)
    inserted: list[LinkInsertion] = []
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        if any(name.startswith("_xmlsignatures/") for name in names):
            raise LinkProjectionError("digitally signed DOCX packages are not mutated")
        for part, insertions in by_part.items():
            xml_name, rel_name = part_members(part, LinkProjectionError)
            if xml_name not in names:
                for insertion in insertions:
                    review.append(_projection_review(insertion, "Word part is missing"))
                continue
            root = parse_word_xml(archive.read(xml_name), LinkProjectionError)
            relationships = _relationship_root(
                archive.read(rel_name) if rel_name in names else None
            )
            paragraphs = paragraphs_for_part(root, part, LinkProjectionError)
            grouped: dict[int, list[LinkInsertion]] = {}
            for insertion in insertions:
                grouped.setdefault(insertion.paragraph_index, []).append(insertion)
            for paragraph_index, paragraph_insertions in grouped.items():
                if paragraph_index >= len(paragraphs):
                    for insertion in paragraph_insertions:
                        review.append(_projection_review(insertion, "paragraph is missing"))
                    continue
                paragraph = paragraphs[paragraph_index]
                for insertion in sorted(
                    paragraph_insertions, key=lambda value: value.start, reverse=True
                ):
                    reason = _apply_one(paragraph, insertion, relationships)
                    if reason is None:
                        inserted.append(insertion)
                    else:
                        review.append(_projection_review(insertion, reason))
            modified[xml_name] = etree.tostring(
                root, xml_declaration=True, encoding="UTF-8", standalone=True
            )
            relationship_bytes = etree.tostring(
                relationships, xml_declaration=True, encoding="UTF-8", standalone=True
            )
            if rel_name in names:
                modified[rel_name] = relationship_bytes
            else:
                added[rel_name] = relationship_bytes

        temporary = write_docx_package(archive, output, modified, added)

    try:
        projected = inspect_brief_docx(temporary)
        original_text = tuple((p.part, p.paragraph_index, p.text) for p in inspection.paragraphs)
        projected_text = tuple((p.part, p.paragraph_index, p.text) for p in projected.paragraphs)
        if original_text != projected_text:
            raise LinkProjectionError("visible text changed during hyperlink projection")
        os.replace(temporary, output)
        output.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    output_sha256 = _hash_path(output)
    return LinkApplyResult(
        inspection.sha256,
        _plan_hash(plan),
        output_sha256,
        len(inserted),
        tuple(review),
        tuple(inserted),
    )


def write_link_manifest(
    path: Path,
    plan: AuthorityLinkPlan,
    result: LinkApplyResult,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    payload = {
        "schema_version": 1,
        "input_sha256": result.input_sha256,
        "plan_sha256": result.plan_sha256,
        "output_sha256": result.output_sha256,
        "inserted_count": result.inserted_count,
        "insertions": [asdict(value) for value in plan.insertions],
        "review": [asdict(value) for value in result.review],
    }
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return path


def _apply_one(
    paragraph: etree._Element,
    insertion: LinkInsertion,
    relationships: etree._Element,
) -> str | None:
    text = visible_text(paragraph)
    if not 0 <= insertion.start < insertion.end <= len(text):
        return "citation span is outside the paragraph"
    if text[insertion.start : insertion.end] != insertion.expected_text:
        return "citation text no longer matches the plan"

    positions: list[tuple[etree._Element, int, int]] = []
    cursor = 0
    for child in paragraph:
        chunk = visible_text(child)
        end = cursor + len(chunk)
        if cursor < insertion.end and insertion.start < end:
            positions.append((child, cursor, end))
        cursor = end
    if not positions or any(etree.QName(child).localname != "r" for child, _, _ in positions):
        return "citation crosses a field, hyperlink, tracked change, or unsupported wrapper"
    runs = [child for child, _, _ in positions]
    if any(not _plain_run(run) for run in runs):
        return "citation uses a complex Word run that is not safe to split"

    first_run, first_start, _ = positions[0]
    last_run, last_start, last_end = positions[-1]
    before = _slice_run(first_run, 0, insertion.start - first_start)
    after = _slice_run(last_run, insertion.end - last_start, last_end - last_start)
    middle: list[etree._Element] = []
    for run, run_start, run_end in positions:
        sliced = _slice_run(
            run,
            max(0, insertion.start - run_start),
            min(run_end - run_start, insertion.end - run_start),
        )
        if sliced is not None:
            _apply_hyperlink_style(sliced)
            middle.append(sliced)
    if not middle:
        return "citation has no splittable Word text"

    relationship_id = _relationship_id(relationships, insertion.url)
    hyperlink = etree.Element(f"{{{W_NS}}}hyperlink")
    hyperlink.set(f"{{{R_NS}}}id", relationship_id)
    hyperlink.set(f"{{{W_NS}}}history", "1")
    for run in middle:
        hyperlink.append(run)

    index = paragraph.index(first_run)
    for run in runs:
        paragraph.remove(run)
    replacements = [value for value in (before, hyperlink, after) if value is not None]
    for offset, value in enumerate(replacements):
        paragraph.insert(index + offset, value)
    return None


def _plain_run(run: etree._Element) -> bool:
    return all(etree.QName(child).localname in {*_TEXT_TAGS, "rPr"} for child in run)


def _slice_run(run: etree._Element, start: int, end: int) -> etree._Element | None:
    if end <= start:
        return None
    clone = copy.deepcopy(run)
    cursor = 0
    kept = False
    for child in list(clone):
        tag = etree.QName(child).localname
        if tag == "rPr":
            continue
        length = len(child.text or "") if tag == "t" else 1
        overlap_start = max(start, cursor)
        overlap_end = min(end, cursor + length)
        if overlap_end <= overlap_start:
            clone.remove(child)
        elif tag == "t":
            child.text = (child.text or "")[overlap_start - cursor : overlap_end - cursor]
            update_xml_space(child)
            kept = True
        else:
            kept = True
        cursor += length
    return clone if kept else None


def _apply_hyperlink_style(run: etree._Element) -> None:
    run_properties = run.find(f"{{{W_NS}}}rPr")
    if run_properties is None:
        run_properties = etree.Element(f"{{{W_NS}}}rPr")
        run.insert(0, run_properties)
    style = run_properties.find(f"{{{W_NS}}}rStyle")
    if style is None:
        style = etree.Element(f"{{{W_NS}}}rStyle")
        run_properties.insert(0, style)
    style.set(f"{{{W_NS}}}val", "Hyperlink")


def _relationship_id(root: etree._Element, url: str) -> str:
    used = {relation.get("Id", "") for relation in root}
    for relation in root:
        if (
            relation.get("Type") == HYPERLINK_REL
            and relation.get("TargetMode") == "External"
            and relation.get("Target") == url
        ):
            return relation.get("Id", "")
    number = 1
    while f"rId{number}" in used:
        number += 1
    relationship_id = f"rId{number}"
    relation = etree.SubElement(root, f"{{{REL_NS}}}Relationship")
    relation.set("Id", relationship_id)
    relation.set("Type", HYPERLINK_REL)
    relation.set("Target", url)
    relation.set("TargetMode", "External")
    return relationship_id


def _relationship_root(data: bytes | None) -> etree._Element:
    if data is None:
        return etree.Element(f"{{{REL_NS}}}Relationships")
    root = parse_word_xml(data, LinkProjectionError)
    if etree.QName(root).localname != "Relationships":
        raise LinkProjectionError("Word relationship part is invalid")
    return root




def _validate_nonoverlap(by_part: dict[str, list[LinkInsertion]]) -> None:
    for insertions in by_part.values():
        by_paragraph: dict[int, list[LinkInsertion]] = {}
        for insertion in insertions:
            by_paragraph.setdefault(insertion.paragraph_index, []).append(insertion)
        for values in by_paragraph.values():
            ordered = sorted(values, key=lambda value: (value.start, value.end))
            if any(left.end > right.start for left, right in itertools.pairwise(ordered)):
                raise LinkProjectionError("link plan contains overlapping insertions")


def _projection_review(insertion: LinkInsertion, reason: str) -> LinkReviewItem:
    return LinkReviewItem(
        insertion.part,
        insertion.paragraph_index,
        insertion.expected_text,
        reason,
        insertion.start,
        insertion.end,
    )


def _plan_hash(plan: AuthorityLinkPlan) -> str:
    payload = json.dumps(asdict(plan), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
