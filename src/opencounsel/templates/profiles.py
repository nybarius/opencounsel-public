from __future__ import annotations

import re
import tomllib
from datetime import date
from importlib import resources
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

PROFILE_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,95}$")
MAX_PROFILE_BYTES = 128 * 1024

FontKind = Literal["proportional-serif", "monospace"]
DocumentType = Literal[
    "appellant-brief",
    "principal-brief",
    "motion-memorandum",
]
HeadingNumbering = Literal[
    "point-roman",
    "roman-outline",
]


class FilingProfileError(ValueError):
    """Raised when a filing profile is missing, stale, or malformed."""


class _ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RuleSource(_ClosedModel):
    title: str
    authority: str
    url: str

    @field_validator("title", "authority")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("source fields must not be blank")
        return value

    @field_validator("url")
    @classmethod
    def _official_https_url(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("rule sources must use HTTPS")
        return value


class PageRules(_ClosedModel):
    paper: Literal["letter"]
    min_margin_in: float
    page_numbering: Literal["consecutive", "consecutive-bottom-center"]

    @field_validator("min_margin_in")
    @classmethod
    def _sensible_margin(cls, value: float) -> float:
        if not 0.5 <= value <= 2:
            raise ValueError("minimum margin is outside the supported range")
        return value


class TypographyRules(_ClosedModel):
    allowed_font_kinds: tuple[FontKind, ...]
    body_min_pt: float
    footnote_min_pt: float
    body_line_spacing: Literal["double"]
    single_spaced_parts: tuple[
        Literal["headings", "footnotes", "block-quotes"], ...
    ]

    @field_validator("allowed_font_kinds")
    @classmethod
    def _font_kinds_are_unique(cls, value: tuple[FontKind, ...]) -> tuple[FontKind, ...]:
        if not value or len(value) != len(set(value)):
            raise ValueError("allowed font kinds must be nonempty and unique")
        return value

    @field_validator("body_min_pt", "footnote_min_pt")
    @classmethod
    def _sensible_font_size(cls, value: float) -> float:
        if not 8 <= value <= 24:
            raise ValueError("font size is outside the supported range")
        return value


class LengthRules(_ClosedModel):
    maximum_words: int
    excluded_parts: tuple[str, ...]
    certification_required: bool

    @field_validator("maximum_words")
    @classmethod
    def _positive_maximum(cls, value: int) -> int:
        if value < 1:
            raise ValueError("maximum words must be positive")
        return value


class StructureRules(_ClosedModel):
    required_sections: tuple[str, ...]
    distinct_point_headings: bool
    heading_numbering: HeadingNumbering

    @field_validator("required_sections")
    @classmethod
    def _sections_are_unique(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not item.strip() for item in value) or len(value) != len(set(value)):
            raise ValueError("required sections must be nonempty and unique")
        return value


class ElectronicRules(_ClosedModel):
    text_searchable_pdf: bool
    metadata_removal: bool
    bookmarks: Literal[
        "not-specified",
        "required-over-4500-words",
        "required-for-electronic-memoranda",
    ]
    docket_hyperlinks: Literal[
        "not-specified",
        "required-for-nyscef-citations",
    ]
    pdf_page_labels: bool


class FilingProfile(_ClosedModel):
    schema_version: Literal[1]
    profile_id: str
    version: str
    jurisdiction: str
    court: str
    document_type: DocumentType
    effective_from: date
    effective_to: date | None = None
    last_verified: date
    page: PageRules
    typography: TypographyRules
    length: LengthRules | None = None
    structure: StructureRules
    electronic: ElectronicRules
    sources: tuple[RuleSource, ...]

    @field_validator("profile_id")
    @classmethod
    def _stable_profile_id(cls, value: str) -> str:
        if not PROFILE_ID_RE.fullmatch(value):
            raise ValueError("profile_id must be a lowercase stable identifier")
        return value

    @field_validator("version", "jurisdiction", "court")
    @classmethod
    def _required_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("profile text fields must not be blank")
        return value

    @field_validator("sources")
    @classmethod
    def _sources_are_required(cls, value: tuple[RuleSource, ...]) -> tuple[RuleSource, ...]:
        if not value:
            raise ValueError("at least one primary rule source is required")
        return value

    @model_validator(mode="after")
    def _dates_are_ordered(self) -> Self:
        if self.effective_to is not None and self.effective_to < self.effective_from:
            raise ValueError("effective_to precedes effective_from")
        if self.last_verified < self.effective_from:
            raise ValueError("last_verified precedes effective_from")
        return self

    def ensure_effective(self, as_of: date) -> None:
        if as_of < self.effective_from or (
            self.effective_to is not None and as_of > self.effective_to
        ):
            raise FilingProfileError(
                f"filing profile {self.profile_id!r} is not effective on {as_of.isoformat()}"
            )


def load_filing_profile(path: Path) -> FilingProfile:
    if not path.is_file() or path.is_symlink() or path.suffix.lower() != ".toml":
        raise FilingProfileError("filing profile must be a regular TOML file")
    if path.stat().st_size > MAX_PROFILE_BYTES:
        raise FilingProfileError("filing profile exceeds the 128 KiB limit")
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise FilingProfileError("filing profile is malformed") from exc
    return _validate_profile(data)


def list_bundled_filing_profiles() -> tuple[FilingProfile, ...]:
    package = resources.files("opencounsel.templates.profile_data")
    profiles = [
        _load_resource_profile(resource)
        for resource in sorted(package.iterdir(), key=lambda item: item.name)
        if resource.name.endswith(".toml")
    ]
    ids = [profile.profile_id for profile in profiles]
    if len(ids) != len(set(ids)):
        raise FilingProfileError("bundled filing profile IDs are not unique")
    return tuple(profiles)


def get_bundled_filing_profile(
    profile_id: str, *, as_of: date | None = None
) -> FilingProfile:
    for profile in list_bundled_filing_profiles():
        if profile.profile_id == profile_id:
            profile.ensure_effective(as_of or date.today())
            return profile
    raise FilingProfileError(f"unknown filing profile: {profile_id}")


def _load_resource_profile(resource: resources.abc.Traversable) -> FilingProfile:
    try:
        text = resource.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise FilingProfileError("bundled filing profile is unreadable") from exc
    if len(text.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise FilingProfileError("filing profile exceeds the 128 KiB limit")
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise FilingProfileError("bundled filing profile is malformed") from exc
    return _validate_profile(data)


def _validate_profile(data: object) -> FilingProfile:
    try:
        return FilingProfile.model_validate(data)
    except ValidationError as exc:
        if any(error["type"] == "extra_forbidden" for error in exc.errors()):
            message = "filing profile contains unknown fields"
        else:
            message = "filing profile is malformed"
        raise FilingProfileError(message) from exc
