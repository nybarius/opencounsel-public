from __future__ import annotations

import hashlib
import itertools
import os
import shutil
import tempfile
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from lxml import etree

from opencounsel.briefs.docx import NS, BriefDocxError, inspect_brief_docx
from opencounsel.briefs.ir import BriefInspection, BriefParagraph
from opencounsel.briefs.ooxml import (
    paragraphs_for_part,
    parse_word_xml,
    part_members,
    update_xml_space,
    visible_text,
    visible_text_spans,
    write_docx_package,
)
from opencounsel.briefs.proof import ProofCandidate, ProofPlan
from opencounsel.contracts.models import CorrectionRecord

UNSAFE_ANCESTORS = {"fldSimple", "hyperlink", "ins", "moveTo"}


class ProofProjectionError(BriefDocxError):
    """Raised when a proof projection would violate the Word safety contract."""


@dataclass(frozen=True, slots=True)
class ProofApplyResult:
    input_sha256: str
    output_sha256: str
    corrections: tuple[CorrectionRecord, ...]
    applied_count: int
    review_count: int


def apply_proof_corrections(
    source: Path,
    output: Path,
    plan: ProofPlan,
) -> ProofApplyResult:
    """Apply representable proof edits to a new DOCX and verify all visible text."""
    inspection = inspect_brief_docx(source)
    if inspection.sha256 != plan.input_sha256:
        raise ProofProjectionError("proof plan does not match the input DOCX hash")
    if source.resolve() == output.resolve():
        raise ProofProjectionError("proof projection must write a new DOCX")
    if output.exists() or output.is_symlink():
        raise ProofProjectionError("proof projection output already exists")
    _validate_plan(inspection, plan)
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output.parent.chmod(0o700)

    paragraph_ir = {
        (paragraph.part, paragraph.paragraph_index): paragraph
        for paragraph in inspection.paragraphs
    }
    by_part: dict[str, list[ProofCandidate]] = defaultdict(list)
    for correction in plan.corrections:
        by_part[correction.part].append(correction)

    decisions: dict[str, CorrectionRecord] = {}
    modified: dict[str, bytes] = {}
    with zipfile.ZipFile(source) as archive:
        names = set(archive.namelist())
        signed = any(name.startswith("_xmlsignatures/") for name in names)
        if signed:
            for correction in plan.corrections:
                decisions[correction.correction_id] = _record(
                    correction,
                    "review-only",
                    "digitally signed package was not changed",
                )
        else:
            for part, corrections in by_part.items():
                xml_name, _ = part_members(part, ProofProjectionError)
                if xml_name not in names:
                    for correction in corrections:
                        decisions[correction.correction_id] = _record(
                            correction, "review-only", "Word part is missing"
                        )
                    continue
                root = parse_word_xml(archive.read(xml_name), ProofProjectionError)
                paragraphs = paragraphs_for_part(root, part, ProofProjectionError)
                grouped: dict[int, list[ProofCandidate]] = defaultdict(list)
                for correction in corrections:
                    grouped[correction.paragraph_index].append(correction)
                part_changed = False
                for paragraph_index, paragraph_corrections in grouped.items():
                    if paragraph_index >= len(paragraphs):
                        for correction in paragraph_corrections:
                            decisions[correction.correction_id] = _record(
                                correction, "review-only", "paragraph is missing"
                            )
                        continue
                    paragraph = paragraphs[paragraph_index]
                    source_paragraph = paragraph_ir[(part, paragraph_index)]
                    for correction in sorted(
                        paragraph_corrections,
                        key=lambda value: value.start_offset,
                        reverse=True,
                    ):
                        reason = _apply_one(paragraph, source_paragraph, correction)
                        if reason is None:
                            decisions[correction.correction_id] = _record(
                                correction, "applied"
                            )
                            part_changed = True
                        else:
                            decisions[correction.correction_id] = _record(
                                correction, "review-only", reason
                            )
                if part_changed:
                    modified[xml_name] = etree.tostring(
                        root, xml_declaration=True, encoding="UTF-8", standalone=True
                    )

        temporary = (
            write_docx_package(archive, output, modified)
            if modified
            else _copy_to_temporary(source, output)
        )

    ordered = tuple(decisions[item.correction_id] for item in plan.corrections)
    applied = tuple(item for item in ordered if item.application_status == "applied")
    try:
        projected = inspect_brief_docx(temporary)
        _verify_visible_text(inspection, projected, applied)
        os.replace(temporary, output)
        output.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise

    return ProofApplyResult(
        input_sha256=inspection.sha256,
        output_sha256=_hash_path(output),
        corrections=ordered,
        applied_count=len(applied),
        review_count=len(ordered) - len(applied),
    )


def _validate_plan(inspection: BriefInspection, plan: ProofPlan) -> None:
    paragraphs = {
        (paragraph.part, paragraph.paragraph_index): paragraph.text
        for paragraph in inspection.paragraphs
    }
    seen: set[str] = set()
    grouped: dict[tuple[str, int], list[ProofCandidate]] = defaultdict(list)
    for correction in plan.corrections:
        if correction.correction_id in seen:
            raise ProofProjectionError("proof plan contains duplicate correction ids")
        seen.add(correction.correction_id)
        text = paragraphs.get((correction.part, correction.paragraph_index))
        if text is None:
            raise ProofProjectionError("proof plan references a missing paragraph")
        if not 0 <= correction.start_offset < correction.end_offset <= len(text):
            raise ProofProjectionError("proof correction span is outside the paragraph")
        if text[correction.start_offset : correction.end_offset] != correction.original_text:
            raise ProofProjectionError("proof correction text no longer matches the plan")
        if (
            not correction.original_text[:-1]
            or set(correction.original_text[:-1]) != {" "}
            or correction.original_text[-1] not in ",;:!?"
            or correction.replacement_text != correction.original_text[-1]
        ):
            raise ProofProjectionError("proof plan contains an unsupported correction")
        grouped[(correction.part, correction.paragraph_index)].append(correction)
    for corrections in grouped.values():
        ordered = sorted(corrections, key=lambda item: item.start_offset)
        if any(
            left.end_offset > right.start_offset
            for left, right in itertools.pairwise(ordered)
        ):
            raise ProofProjectionError("proof plan contains overlapping corrections")


def _apply_one(
    paragraph: etree._Element,
    source_paragraph: BriefParagraph,
    correction: ProofCandidate,
) -> str | None:
    text = visible_text(paragraph)
    if text[correction.start_offset : correction.end_offset] != correction.original_text:
        return "paragraph text changed before projection"
    if any(
        link.start < correction.end_offset and correction.start_offset < link.end
        for link in source_paragraph.hyperlinks
    ):
        return "target crosses a hyperlink"
    if paragraph.xpath(".//w:fldChar | .//w:instrText", namespaces=NS):
        return "paragraph contains a Word field"

    removals: dict[etree._Element, list[int]] = defaultdict(list)
    spans = visible_text_spans(paragraph)
    for offset in range(correction.start_offset, correction.end_offset - 1):
        span = next((item for item in spans if item.start <= offset < item.end), None)
        if span is None or span.node is None:
            return "spacing is not represented by editable Word text"
        if (span.node.text or "")[offset - span.start] != " ":
            return "proof target is not an ASCII space"
        ancestors = {etree.QName(item).localname for item in span.node.iterancestors()}
        if ancestors & UNSAFE_ANCESTORS:
            return "target crosses a hyperlink, field, or tracked change"
        removals[span.node].append(offset - span.start)

    for node, indexes in removals.items():
        characters = list(node.text or "")
        for index in sorted(indexes, reverse=True):
            del characters[index]
        node.text = "".join(characters)
        update_xml_space(node)
    return None


def _record(
    correction: ProofCandidate,
    status: Literal["applied", "review-only"],
    reason: str | None = None,
) -> CorrectionRecord:
    application_status: Literal["applied", "review-only"] = status
    note = (
        f"{correction.note} Applied to corrected DOCX; review in Word Compare."
        if reason is None
        else f"{correction.note} Not applied automatically: {reason}."
    )
    return CorrectionRecord(
        correction_id=correction.correction_id,
        stage="proof",
        basis_sha256=correction.basis_sha256,
        part=correction.part,
        paragraph_index=correction.paragraph_index,
        start_offset=correction.start_offset,
        end_offset=correction.end_offset,
        original_text=correction.original_text,
        replacement_text=correction.replacement_text,
        note=note,
        application_status=application_status,
        review_status="pending",
    )


def _verify_visible_text(
    original: BriefInspection,
    projected: BriefInspection,
    applied: tuple[CorrectionRecord, ...],
) -> None:
    expected = {
        (paragraph.part, paragraph.paragraph_index): paragraph.text
        for paragraph in original.paragraphs
    }
    grouped: dict[tuple[str, int], list[CorrectionRecord]] = defaultdict(list)
    for correction in applied:
        grouped[(correction.part, correction.paragraph_index)].append(correction)
    for key, corrections in grouped.items():
        text = expected[key]
        for correction in sorted(
            corrections, key=lambda item: item.start_offset, reverse=True
        ):
            text = (
                text[: correction.start_offset]
                + correction.replacement_text
                + text[correction.end_offset :]
            )
        expected[key] = text
    actual = {
        (paragraph.part, paragraph.paragraph_index): paragraph.text
        for paragraph in projected.paragraphs
    }
    if actual != expected:
        raise ProofProjectionError("visible text differs from the approved proof plan")


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
