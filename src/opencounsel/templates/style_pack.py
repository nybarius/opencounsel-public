from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from opencounsel.templates.profiles import FilingProfile, FilingProfileError, FontKind

Alignment = Literal["left", "justified"]


@dataclass(frozen=True, slots=True)
class WordStylePack:
    schema_version: int
    style_pack_id: str
    version: str
    font_family: str
    font_kind: FontKind
    body_alignment: Alignment
    hyperlink_color: str
    hyperlink_underline: bool


@dataclass(frozen=True, slots=True)
class ResolvedWordStyle:
    profile_id: str
    style_pack_id: str
    font_family: str
    font_kind: FontKind
    body_font_size_pt: float
    footnote_font_size_pt: float
    body_alignment: Alignment
    hyperlink_color: str
    hyperlink_underline: bool


CLEAN_SERIF_STYLE_PACK = WordStylePack(
    schema_version=1,
    style_pack_id="opencounsel-clean-serif",
    version="2026.8",
    font_family="Times New Roman",
    font_kind="proportional-serif",
    body_alignment="justified",
    hyperlink_color="000000",
    hyperlink_underline=True,
)


def resolve_word_style(
    profile: FilingProfile,
    style_pack: WordStylePack = CLEAN_SERIF_STYLE_PACK,
) -> ResolvedWordStyle:
    if style_pack.schema_version != 1:
        raise FilingProfileError("unsupported Word style-pack schema version")
    if style_pack.font_kind not in profile.typography.allowed_font_kinds:
        raise FilingProfileError(
            f"style-pack font kind {style_pack.font_kind!r} is not allowed by "
            f"{profile.profile_id}"
        )
    return ResolvedWordStyle(
        profile_id=profile.profile_id,
        style_pack_id=style_pack.style_pack_id,
        font_family=style_pack.font_family,
        font_kind=style_pack.font_kind,
        body_font_size_pt=profile.typography.body_min_pt,
        footnote_font_size_pt=profile.typography.footnote_min_pt,
        body_alignment=style_pack.body_alignment,
        hyperlink_color=style_pack.hyperlink_color,
        hyperlink_underline=style_pack.hyperlink_underline,
    )
