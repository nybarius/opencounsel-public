from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class StyleBinding:
    semantic_role: str
    word_style_name: str
    toc_level: int | None = None


@dataclass(frozen=True, slots=True)
class TemplateManifest:
    schema_version: int
    template_id: str
    version: str
    template_sha256: str
    styles: tuple[StyleBinding, ...]
    slots: tuple[str, ...]
    filing_profile_id: str | None = None
    style_pack_id: str | None = None


@dataclass(frozen=True, slots=True)
class TemplateValidation:
    template_id: str
    version: str
    template_sha256: str
    section_count: int
    bound_roles: tuple[str, ...]
