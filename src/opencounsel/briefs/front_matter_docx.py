from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from lxml import etree

from opencounsel.briefs.docx import NS, W_NS, BriefDocxError, inspect_brief_docx
from opencounsel.briefs.ir import BriefParagraph
from opencounsel.briefs.ooxml import (
    paragraphs_for_part,
    parse_word_xml,
    part_members,
    update_xml_space,
    visible_text,
    visible_text_spans,
    write_docx_package,
)
from opencounsel.briefs.word_fields import (
    ta_field_runs,
    tc_field_runs,
    toa_field_runs,
    toc_field_runs,
)
from opencounsel.contracts.models import (
    CorrectionRecord,
    FrontMatterSource,
)

_TRACKED_ANCESTORS = {"del", "ins", "moveFrom", "moveTo"}
_MARKER_ITEM_TYPES = {"toc-heading", "toa-authority"}


class FrontMatterProjectionError(BriefDocxError):
    """Raised when a Word front-matter projection violates its hash or safety plan."""


@dataclass(frozen=True, slots=True)
class FrontMatterProjectionResult:
    input_sha256: str
    output_sha256: str
    corrections: tuple[CorrectionRecord, ...]
    toc_marker_candidate_count: int
    toc_marker_inserted_count: int
    toa_marker_candidate_count: int
    toa_marker_inserted_count: int
    toc_field_candidate_count: int
    toc_field_inserted_count: int
    toa_field_candidate_count: int
    toa_field_inserted_count: int
    existing_marker_count: int
    applied_count: int
    review_count: int


@dataclass(frozen=True, slots=True)
class _FieldCandidate:
    correction_id: str
    basis_sha256: str
    stage: Literal["toc", "toa"]
    item_type: Literal["toc-heading", "toa-authority", "toc-field", "toa-field"]
    part: str
    paragraph_index: int
    start_offset: int
    end_offset: int
    original_text: str
    instruction: str
    runs: tuple[etree._Element, ...]
    precondition_failure: str | None = None


def project_front_matter_fields(
    source: Path,
    output: Path,
    front_matter: FrontMatterSource,
) -> FrontMatterProjectionResult:
    """Insert reviewed TC/TA markers and exact-slot TOC/TOA fields into a new DOCX."""
    inspection = inspect_brief_docx(source)
    if inspection.sha256 != front_matter.brief_sha256:
        raise FrontMatterProjectionError(
            "front-matter source does not match the input DOCX hash"
        )
    if source.resolve() == output.resolve():
        raise FrontMatterProjectionError("front-matter projection must write a new DOCX")
    if output.exists() or output.is_symlink():
        raise FrontMatterProjectionError("front-matter projection output already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)

    paragraphs = {
        (paragraph.part, paragraph.paragraph_index): paragraph
        for paragraph in inspection.paragraphs
    }
    candidates = _field_candidates(front_matter, paragraphs)
    _validate_candidates(candidates, paragraphs)
    decisions: dict[str, tuple[CorrectionRecord, str]] = {}
    modified: dict[str, bytes] = {}

    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        signed = any(name.startswith("_xmlsignatures/") for name in names)
        if signed:
            for candidate in candidates:
                decisions[candidate.correction_id] = (
                    _record(
                        candidate,
                        "review-only",
                        "digitally signed package was not changed",
                    ),
                    "review",
                )
            temporary = _copy_to_temporary(source, output)
        else:
            by_part: dict[str, list[_FieldCandidate]] = defaultdict(list)
            for candidate in candidates:
                by_part[candidate.part].append(candidate)
            for part, part_candidates in by_part.items():
                xml_name, _ = part_members(part, FrontMatterProjectionError)
                if xml_name not in names:
                    for candidate in part_candidates:
                        decisions[candidate.correction_id] = (
                            _record(candidate, "review-only", "Word part is missing"),
                            "review",
                        )
                    continue
                root = parse_word_xml(archive.read(xml_name), FrontMatterProjectionError)
                xml_paragraphs = paragraphs_for_part(
                    root, part, FrontMatterProjectionError
                )
                changed = False
                grouped: dict[int, list[_FieldCandidate]] = defaultdict(list)
                for candidate in part_candidates:
                    grouped[candidate.paragraph_index].append(candidate)
                for paragraph_index, paragraph_candidates in grouped.items():
                    if paragraph_index >= len(xml_paragraphs):
                        for candidate in paragraph_candidates:
                            decisions[candidate.correction_id] = (
                                _record(candidate, "review-only", "paragraph is missing"),
                                "review",
                            )
                        continue
                    paragraph = xml_paragraphs[paragraph_index]
                    for candidate in sorted(
                        paragraph_candidates,
                        key=lambda value: (
                            value.item_type in {"toc-field", "toa-field"},
                            value.end_offset,
                        ),
                        reverse=True,
                    ):
                        if candidate.item_type in _MARKER_ITEM_TYPES:
                            outcome = _insert_marker(paragraph, candidate)
                        else:
                            outcome = _replace_slot(paragraph, candidate)
                        if outcome in {"inserted", "existing"}:
                            note = (
                                "Native Word field was already present and was preserved"
                                if outcome == "existing"
                                else (
                                    "Native Word field was inserted; update fields in Word "
                                    "before filing"
                                )
                            )
                            decisions[candidate.correction_id] = (
                                _record(candidate, "applied", note),
                                outcome,
                            )
                            changed = changed or outcome == "inserted"
                        else:
                            decisions[candidate.correction_id] = (
                                _record(candidate, "review-only", outcome),
                                "review",
                            )
                if changed:
                    modified[xml_name] = etree.tostring(
                        root,
                        xml_declaration=True,
                        encoding="UTF-8",
                        standalone=True,
                    )
            temporary = (
                write_docx_package(archive, output, modified)
                if modified
                else _copy_to_temporary(source, output)
            )

    ordered = tuple(decisions[item.correction_id][0] for item in candidates)
    outcomes = {key: outcome for key, (_record_value, outcome) in decisions.items()}
    try:
        projected = inspect_brief_docx(temporary)
        if [paragraph.text for paragraph in projected.paragraphs] != [
            paragraph.text for paragraph in inspection.paragraphs
        ]:
            raise FrontMatterProjectionError(
                "front-matter projection changed visible document text"
            )
        os.replace(temporary, output)
        output.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    def inserted(item_type: str) -> int:
        return sum(
            candidate.item_type == item_type
            and outcomes[candidate.correction_id] == "inserted"
            for candidate in candidates
        )

    toc_markers = sum(item.item_type == "toc-heading" for item in candidates)
    toa_markers = sum(item.item_type == "toa-authority" for item in candidates)
    toc_fields = sum(item.item_type == "toc-field" for item in candidates)
    toa_fields = sum(item.item_type == "toa-field" for item in candidates)
    existing = sum(outcome == "existing" for outcome in outcomes.values())
    review = sum(outcome == "review" for outcome in outcomes.values())
    return FrontMatterProjectionResult(
        input_sha256=inspection.sha256,
        output_sha256=_hash_path(output),
        corrections=ordered,
        toc_marker_candidate_count=toc_markers,
        toc_marker_inserted_count=inserted("toc-heading"),
        toa_marker_candidate_count=toa_markers,
        toa_marker_inserted_count=inserted("toa-authority"),
        toc_field_candidate_count=toc_fields,
        toc_field_inserted_count=inserted("toc-field"),
        toa_field_candidate_count=toa_fields,
        toa_field_inserted_count=inserted("toa-field"),
        existing_marker_count=existing,
        applied_count=len(candidates) - review,
        review_count=review,
    )


def _field_candidates(
    front_matter: FrontMatterSource,
    paragraphs: Mapping[tuple[str, int], BriefParagraph],
) -> tuple[_FieldCandidate, ...]:
    candidates: list[_FieldCandidate] = []
    slot_texts = [
        paragraph.text
        for (part, _index), paragraph in paragraphs.items()
        if part == "document" and paragraph.text in {"[TOC]", "[TOA]"}
    ]
    project_toc = slot_texts.count("[TOC]") == 1
    project_toa = slot_texts.count("[TOA]") == 1
    for toc_entry in front_matter.toc if project_toc else ():
        paragraph = paragraphs.get((toc_entry.part, toc_entry.paragraph_index))
        text = paragraph.text if paragraph is not None else toc_entry.heading
        runs = tc_field_runs(toc_entry.heading, toc_entry.level)
        candidates.append(
            _candidate(
                front_matter.brief_sha256,
                "toc",
                "toc-heading",
                toc_entry.part,
                toc_entry.paragraph_index,
                0,
                len(text),
                text,
                runs,
                toc_entry.entry_id,
            )
        )
    for toa_entry in front_matter.toa if project_toa else ():
        runs = ta_field_runs(
            toa_entry.display_name,
            toa_entry.short_name,
            toa_entry.word_category,
            italic_spans=toa_entry.italic_spans,
        )
        for location in toa_entry.locations:
            candidates.append(
                _candidate(
                    front_matter.brief_sha256,
                    "toa",
                    "toa-authority",
                    location.part,
                    location.paragraph_index,
                    location.start_offset,
                    location.end_offset,
                    location.original_text,
                    runs,
                    toa_entry.authority_id,
                )
            )
    for (part, index), paragraph in paragraphs.items():
        text = paragraph.text
        if part != "document" or text not in {"[TOC]", "[TOA]"}:
            continue
        stage: Literal["toc", "toa"] = "toc" if text == "[TOC]" else "toa"
        item_type: Literal["toc-field", "toa-field"] = (
            "toc-field" if stage == "toc" else "toa-field"
        )
        runs = toc_field_runs(text) if stage == "toc" else toa_field_runs(text)
        candidates.append(
            _candidate(
                front_matter.brief_sha256,
                stage,
                item_type,
                part,
                index,
                0,
                len(text),
                text,
                runs,
                text,
                precondition_failure=(
                    f"multiple exact {text} slots make placement ambiguous"
                    if slot_texts.count(text) > 1
                    else None
                ),
            )
        )
    order = {"toc-field": 0, "toa-field": 1, "toc-heading": 2, "toa-authority": 3}
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                order[item.item_type],
                item.part,
                item.paragraph_index,
                item.start_offset,
                item.correction_id,
            ),
        )
    )


def _candidate(
    basis_sha256: str,
    stage: Literal["toc", "toa"],
    item_type: Literal["toc-heading", "toa-authority", "toc-field", "toa-field"],
    part: str,
    paragraph_index: int,
    start_offset: int,
    end_offset: int,
    original_text: str,
    runs: tuple[etree._Element, ...],
    semantic_id: str,
    *,
    precondition_failure: str | None = None,
) -> _FieldCandidate:
    instruction_chunks: list[str] = []
    for run in runs:
        instruction_chunks.extend(
            cast(list[str], run.xpath("./w:instrText/text()", namespaces=NS))
        )
    instruction = "".join(instruction_chunks)
    body = json.dumps(
        {
            "basis_sha256": basis_sha256,
            "item_type": item_type,
            "semantic_id": semantic_id,
            "part": part,
            "paragraph_index": paragraph_index,
            "start_offset": start_offset,
            "end_offset": end_offset,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return _FieldCandidate(
        correction_id=f"corr-{hashlib.sha256(body).hexdigest()}",
        basis_sha256=basis_sha256,
        stage=stage,
        item_type=item_type,
        part=part,
        paragraph_index=paragraph_index,
        start_offset=start_offset,
        end_offset=end_offset,
        original_text=original_text,
        instruction=instruction,
        runs=runs,
        precondition_failure=precondition_failure,
    )


def _validate_candidates(
    candidates: tuple[_FieldCandidate, ...],
    paragraphs: Mapping[tuple[str, int], BriefParagraph],
) -> None:
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.correction_id in seen:
            raise FrontMatterProjectionError(
                "front-matter plan contains duplicate correction ids"
            )
        seen.add(candidate.correction_id)
        paragraph = paragraphs.get((candidate.part, candidate.paragraph_index))
        if paragraph is None:
            raise FrontMatterProjectionError("front-matter plan references a missing paragraph")
        text = paragraph.text
        if not 0 <= candidate.start_offset < candidate.end_offset <= len(text):
            raise FrontMatterProjectionError("front-matter span is outside the paragraph")
        if text[candidate.start_offset : candidate.end_offset] != candidate.original_text:
            raise FrontMatterProjectionError(
                "front-matter text no longer matches the source plan"
            )


def _insert_marker(paragraph: etree._Element, candidate: _FieldCandidate) -> str:
    text = visible_text(paragraph)
    if text[candidate.start_offset : candidate.end_offset] != candidate.original_text:
        return "paragraph text changed before projection"
    spans = visible_text_spans(paragraph)
    span = next(
        (
            value
            for value in spans
            if value.node is not None and value.start < candidate.end_offset <= value.end
        ),
        None,
    )
    if span is None or span.node is None:
        return "field marker has no editable Word text endpoint"
    ancestors = list(span.node.iterancestors())
    ancestor_names = {etree.QName(value).localname for value in ancestors}
    if ancestor_names & _TRACKED_ANCESTORS:
        return "target is inside a tracked change"
    if ancestor_names & {"fldSimple"} or any(
        value.xpath("./w:fldChar | ./w:instrText", namespaces=NS) for value in ancestors
    ):
        return "target is inside an existing Word field"

    hyperlink = next(
        (value for value in ancestors if etree.QName(value).localname == "hyperlink"),
        None,
    )
    if hyperlink is not None:
        hyperlink_spans = [
            value
            for value in spans
            if value.node is not None and hyperlink in value.node.iterancestors()
        ]
        if not hyperlink_spans or candidate.end_offset != max(
            value.end for value in hyperlink_spans
        ):
            return "authority endpoint is inside a hyperlink"
        parent = hyperlink.getparent()
        if parent is not paragraph:
            return "hyperlink is inside an unsupported Word wrapper"
        anchor = hyperlink
        if _field_immediately_after(anchor, candidate.instruction):
            return "existing"
    else:
        run = span.node.getparent()
        if run is None or etree.QName(run).localname != "r" or run.getparent() is not paragraph:
            return "field endpoint is inside an unsupported Word wrapper"
        text_nodes = cast(list[etree._Element], run.xpath("./w:t", namespaces=NS))
        if len(text_nodes) != 1 or any(
            etree.QName(child).localname not in {"rPr", "t"} for child in run
        ):
            return "field endpoint is inside a complex Word run"
        local_end = candidate.end_offset - span.start
        if local_end == len(span.node.text or "") and _field_immediately_after(
            run, candidate.instruction
        ):
            return "existing"
        anchor = _split_run(run, span.node, local_end)

    parent = anchor.getparent()
    if parent is None:
        return "field endpoint has no Word parent"
    index = parent.index(anchor)
    for offset, field_run in enumerate(_cloned_runs(candidate.runs), start=1):
        parent.insert(index + offset, field_run)
    return "inserted"


def _replace_slot(paragraph: etree._Element, candidate: _FieldCandidate) -> str:
    if candidate.precondition_failure is not None:
        return candidate.precondition_failure
    if _has_instruction(paragraph, candidate.instruction):
        return "existing"
    if visible_text(paragraph) != candidate.original_text:
        return "front-matter slot text changed before projection"
    if paragraph.xpath(
        ".//w:ins | .//w:del | .//w:moveFrom | .//w:moveTo | .//w:hyperlink",
        namespaces=NS,
    ):
        return "front-matter slot contains a tracked change or hyperlink"
    for child in list(paragraph):
        if etree.QName(child).localname != "pPr":
            paragraph.remove(child)
    for run in _cloned_runs(candidate.runs):
        paragraph.append(run)
    return "inserted"


def _split_run(
    run: etree._Element,
    text_node: etree._Element,
    local_end: int,
) -> etree._Element:
    text = text_node.text or ""
    if local_end >= len(text):
        return run
    if local_end <= 0:
        raise FrontMatterProjectionError("field endpoint does not follow visible text")
    parent = run.getparent()
    if parent is None:
        raise FrontMatterProjectionError("field endpoint run has no parent")
    suffix_run = etree.Element(f"{{{W_NS}}}r")
    properties = run.find(f"{{{W_NS}}}rPr")
    if properties is not None:
        suffix_run.append(copy.deepcopy(properties))
    suffix = etree.SubElement(suffix_run, f"{{{W_NS}}}t")
    suffix.text = text[local_end:]
    update_xml_space(suffix)
    text_node.text = text[:local_end]
    update_xml_space(text_node)
    parent.insert(parent.index(run) + 1, suffix_run)
    return run


def _has_instruction(paragraph: etree._Element, instruction: str) -> bool:
    existing = "".join(
        cast(list[str], paragraph.xpath(".//w:instrText/text()", namespaces=NS))
    )
    return instruction in existing


def _field_immediately_after(anchor: etree._Element, instruction: str) -> bool:
    parent = anchor.getparent()
    if parent is None:
        return False
    siblings = list(parent)
    try:
        cursor = siblings.index(anchor) + 1
    except ValueError:
        return False
    started = False
    chunks: list[str] = []
    for sibling in siblings[cursor : cursor + 32]:
        if etree.QName(sibling).localname != "r":
            return False
        field_types = cast(
            list[str], sibling.xpath("./w:fldChar/@w:fldCharType", namespaces=NS)
        )
        if field_types and field_types[0] == "begin":
            started = True
        if not started:
            if visible_text(sibling):
                return False
            continue
        chunks.extend(
            cast(list[str], sibling.xpath("./w:instrText/text()", namespaces=NS))
        )
        if field_types and field_types[0] == "end":
            return "".join(chunks) == instruction
    return False


def _cloned_runs(runs: tuple[etree._Element, ...]) -> tuple[etree._Element, ...]:
    return tuple(copy.deepcopy(run) for run in runs)


def _record(
    candidate: _FieldCandidate,
    status: Literal["applied", "review-only"],
    reason: str,
) -> CorrectionRecord:
    note = (
        f"{reason}."
        if status == "applied"
        else f"Native Word field was not inserted automatically: {reason}."
    )
    return CorrectionRecord(
        correction_id=candidate.correction_id,
        stage=candidate.stage,
        item_type=candidate.item_type,
        basis_sha256=candidate.basis_sha256,
        part=candidate.part,
        paragraph_index=candidate.paragraph_index,
        start_offset=candidate.start_offset,
        end_offset=candidate.end_offset,
        original_text=candidate.original_text,
        replacement_text=candidate.original_text,
        note=note,
        application_status=status,
        review_status="pending",
    )


def _copy_to_temporary(source: Path, output: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{output.stem}.", suffix=".docx", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(name)
    try:
        shutil.copyfile(source, temporary)
        temporary.chmod(0o600)
        return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "FrontMatterProjectionError",
    "FrontMatterProjectionResult",
    "project_front_matter_fields",
]
