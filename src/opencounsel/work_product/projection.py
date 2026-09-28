from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WordProjectionRequest:
    """Inputs to a Word projection; contains no mutable template state."""

    work_product_revision: str
    template_id: str
    template_version: str
    template_sha256: str


@dataclass(frozen=True, slots=True)
class WordProjectionManifest:
    work_product_revision: str
    template_sha256: str
    output_sha256: str
    transform_version: str
    semantic_id_scheme: str


@dataclass(frozen=True, slots=True)
class FilingLockRequest:
    """Reviewed Word input accepted for reconciliation, not direct publication."""

    projection_sha256: str
    reviewed_word_sha256: str
    accepted_revision: str
