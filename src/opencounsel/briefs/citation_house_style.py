from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CitationHouseStyleFinding:
    phrase: str
    preferred: str
    reason: str


_NONPREFERRED: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(r"\binternal quotation marks and citations omitted\b", re.IGNORECASE),
        "quotation and citations omitted",
        "Omit the unnecessary internal/external qualifier while preserving both disclosures.",
    ),
    (
        re.compile(r"\binternal quotation marks and citation omitted\b", re.IGNORECASE),
        "quotation and citation omitted",
        "Omit the unnecessary internal/external qualifier while preserving both disclosures.",
    ),
    (
        re.compile(r"\binternal quotation marks omitted\b", re.IGNORECASE),
        "quotation omitted",
        "Use the shorter house form; do not describe a quotation as internal.",
    ),
    (
        re.compile(r"\b(?:internal|external) citations omitted\b", re.IGNORECASE),
        "citations omitted",
        "The house style does not distinguish internal from external citations.",
    ),
    (
        re.compile(r"\b(?:internal|external) citation omitted\b", re.IGNORECASE),
        "citation omitted",
        "The house style does not distinguish internal from external citations.",
    ),
    (
        re.compile(r"\b(?:internal|external) quotations omitted\b", re.IGNORECASE),
        "quotations omitted",
        "The house style does not distinguish internal from external quotations.",
    ),
)


def citation_house_style_findings(text: str) -> tuple[CitationHouseStyleFinding, ...]:
    """Flag verbose omission parentheticals without silently rewriting legal text."""
    findings: list[CitationHouseStyleFinding] = []
    for pattern, preferred, reason in _NONPREFERRED:
        for match in pattern.finditer(text):
            findings.append(CitationHouseStyleFinding(match.group(0), preferred, reason))
    return tuple(findings)


__all__ = ["CitationHouseStyleFinding", "citation_house_style_findings"]
