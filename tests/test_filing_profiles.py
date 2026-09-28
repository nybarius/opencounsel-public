from __future__ import annotations

from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from opencounsel.templates.profiles import (
    FilingProfileError,
    get_bundled_filing_profile,
    list_bundled_filing_profiles,
    load_filing_profile,
)
from opencounsel.templates.style_pack import CLEAN_SERIF_STYLE_PACK, resolve_word_style


def test_bundled_profiles_are_specific_to_court_and_document_type() -> None:
    profiles = {profile.profile_id: profile for profile in list_bundled_filing_profiles()}

    assert set(profiles) == {
        "fed-ca2-principal-brief",
        "fed-sdny-edny-motion-memorandum",
        "ny-ad-appellant-brief",
        "ny-coa-principal-brief",
        "ny-commercial-motion-memorandum",
    }
    appellate = profiles["ny-ad-appellant-brief"]
    assert appellate.document_type == "appellant-brief"
    assert appellate.typography.body_min_pt == 14
    assert appellate.typography.footnote_min_pt == 12
    assert appellate.page.min_margin_in == 1
    assert appellate.length is not None
    assert appellate.length.maximum_words == 14_000
    assert appellate.structure.required_sections[:2] == (
        "table-of-contents",
        "table-of-authorities",
    )
    assert appellate.structure.heading_numbering == "point-roman"
    assert any(
        source.url.endswith("Statewide-Practice-Rules-Part-1250.pdf")
        for source in appellate.sources
    )

    federal = profiles["fed-ca2-principal-brief"]
    assert federal.length is not None
    assert federal.length.maximum_words == 13_000
    assert federal.typography.allowed_font_kinds == (
        "proportional-serif",
        "monospace",
    )
    assert federal.structure.heading_numbering == "roman-outline"

    trial = profiles["ny-commercial-motion-memorandum"]
    assert trial.typography.body_min_pt == 12
    assert trial.electronic.docket_hyperlinks == "required-for-nyscef-citations"
    assert trial.structure.heading_numbering == "roman-outline"


def test_profile_selection_is_date_bound_and_fails_closed() -> None:
    profile = get_bundled_filing_profile(
        "ny-ad-appellant-brief", as_of=date(2026, 7, 15)
    )
    assert profile.last_verified == date(2026, 7, 15)

    with pytest.raises(FilingProfileError, match="not effective"):
        get_bundled_filing_profile(
            "ny-ad-appellant-brief", as_of=date(2026, 7, 14)
        )
    with pytest.raises(FilingProfileError, match="unknown filing profile"):
        get_bundled_filing_profile("ny-generic-document")


def test_profile_loader_rejects_unknown_fields(tmp_path: Path) -> None:
    path = tmp_path / "profile.toml"
    path.write_text(
        """schema_version = 1
profile_id = "test-court-test-document"
version = "2026.1"
jurisdiction = "test"
court = "Test Court"
document_type = "motion-memorandum"
effective_from = 2026-01-01
last_verified = 2026-01-01
unexpected = true

[page]
paper = "letter"
min_margin_in = 1.0
page_numbering = "consecutive"

[typography]
allowed_font_kinds = ["proportional-serif"]
body_min_pt = 12
footnote_min_pt = 10
body_line_spacing = "double"
single_spaced_parts = ["headings", "footnotes", "block-quotes"]

[structure]
required_sections = []
distinct_point_headings = false
heading_numbering = "roman-outline"

[electronic]
text_searchable_pdf = false
metadata_removal = false
bookmarks = "not-specified"
docket_hyperlinks = "not-specified"
pdf_page_labels = false

[[sources]]
title = "Test rule"
authority = "Rule 1"
url = "https://example.invalid/rule"
""",
        encoding="utf-8",
    )

    with pytest.raises(FilingProfileError, match="unknown fields"):
        load_filing_profile(path)


def test_clean_style_resolves_to_rule_minima_and_rejects_wrong_font_kind() -> None:
    appellate = get_bundled_filing_profile("ny-ad-appellant-brief")
    resolved = resolve_word_style(appellate, CLEAN_SERIF_STYLE_PACK)

    assert resolved.font_family == "Times New Roman"
    assert resolved.body_font_size_pt == 14
    assert resolved.footnote_font_size_pt == 12
    assert resolved.body_alignment == "justified"

    incompatible = replace(CLEAN_SERIF_STYLE_PACK, font_kind="sans-serif")
    with pytest.raises(FilingProfileError, match="font kind"):
        resolve_word_style(appellate, incompatible)