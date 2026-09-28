from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from opencounsel.briefs.docx import inspect_brief_docx

RULE_ID = "space-before-terminal-punctuation-v1"
SPACE_BEFORE_PUNCTUATION = re.compile(r" +[,;:!?]")


@dataclass(frozen=True, slots=True)
class ProofCandidate:
    correction_id: str
    basis_sha256: str
    stage: Literal["proof"]
    rule_id: str
    part: str
    paragraph_index: int
    start_offset: int
    end_offset: int
    original_text: str
    replacement_text: str
    note: str


@dataclass(frozen=True, slots=True)
class ProofPlan:
    input_sha256: str
    corrections: tuple[ProofCandidate, ...]


def plan_proof_corrections(source: Path) -> ProofPlan:
    """Find only bounded, deterministic punctuation-spacing candidates."""
    inspection = inspect_brief_docx(source)
    corrections: list[ProofCandidate] = []
    for paragraph in inspection.paragraphs:
        for match in SPACE_BEFORE_PUNCTUATION.finditer(paragraph.text):
            original = match.group(0)
            replacement = original[-1]
            payload = {
                "input_sha256": inspection.sha256,
                "rule_id": RULE_ID,
                "part": paragraph.part,
                "paragraph_index": paragraph.paragraph_index,
                "start_offset": match.start(),
                "end_offset": match.end(),
                "original_text": original,
                "replacement_text": replacement,
            }
            digest = hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            corrections.append(
                ProofCandidate(
                    correction_id=f"corr-{digest}",
                    basis_sha256=inspection.sha256,
                    stage="proof",
                    rule_id=RULE_ID,
                    part=paragraph.part,
                    paragraph_index=paragraph.paragraph_index,
                    start_offset=match.start(),
                    end_offset=match.end(),
                    original_text=original,
                    replacement_text=replacement,
                    note=f"Remove {len(original) - 1} space(s) before '{replacement}'.",
                )
            )
    return ProofPlan(inspection.sha256, tuple(corrections))
