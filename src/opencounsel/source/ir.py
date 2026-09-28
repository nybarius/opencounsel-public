from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SourcePage:
    physical_page: int
    record_page: int
    display_cite: str
    text: str


@dataclass(frozen=True, slots=True)
class Artifact:
    role: str
    media_type: str
    member_name: str | None
    sha256: str
    size_bytes: int


@dataclass(frozen=True, slots=True)
class Validation:
    code: str
    status: str
    detail: str


@dataclass(frozen=True, slots=True)
class RoaPackage:
    package: Artifact
    pdf: Artifact
    pages: tuple[SourcePage, ...]
    validations: tuple[Validation, ...]

    @property
    def first_record_page(self) -> int:
        return self.pages[0].record_page

    @property
    def last_record_page(self) -> int:
        return self.pages[-1].record_page

