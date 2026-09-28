"""Versioned data contracts shared by the core and transport adapters."""

from opencounsel.contracts.models import (
    BriefInspectionResult,
    CapabilitiesResult,
    CleanBriefResult,
    CorrectionLedger,
    CorrectionRecord,
    CreateRevisionResult,
    FrontMatterLocation,
    FrontMatterSource,
    ProcessBriefResult,
    ProcessManifest,
    RevisionManifest,
    ToaSourceEntry,
    TocSourceEntry,
)
from opencounsel.contracts.schema import validate_contract

__all__ = [
    "BriefInspectionResult",
    "CapabilitiesResult",
    "CleanBriefResult",
    "CorrectionLedger",
    "CorrectionRecord",
    "CreateRevisionResult",
    "FrontMatterLocation",
    "FrontMatterSource",
    "ProcessBriefResult",
    "ProcessManifest",
    "RevisionManifest",
    "ToaSourceEntry",
    "TocSourceEntry",
    "validate_contract",
]
