from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourceCitation:
    document_key: str
    locator: str


@dataclass(frozen=True, slots=True)
class WorkProductSection:
    section_id: str
    heading: str
    paragraphs: tuple[str, ...]
    citations: tuple[SourceCitation, ...] = ()


@dataclass(frozen=True, slots=True)
class WorkProductIR:
    schema_version: int
    sections: tuple[WorkProductSection, ...]


@dataclass(frozen=True, slots=True)
class FilingIR:
    """Reviewed and locked semantic content accepted for terminal publication."""

    schema_version: int
    sections: tuple[WorkProductSection, ...]
    locked_revision: str

