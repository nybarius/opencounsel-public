from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document

from opencounsel.adapters.citations import extract_citation_candidates
from opencounsel.adapters.word import WordTemplateError, inspect_word_template


def test_extracts_citation_candidates_without_canonicalizing() -> None:
    candidates = extract_citation_candidates(
        "The rule appears in Twombly, 550 U.S. 544, 555 (2007)."
    )

    assert len(candidates) == 1
    assert candidates[0].text == "550 U.S. 544"
    assert candidates[0].normalized_text == "550 U.S. 544"
    assert candidates[0].case_name == "Twombly"
    assert candidates[0].citation_type == "FullCaseCitation"


def test_extracts_reporter_citation_separated_by_nonbreaking_space() -> None:
    source = (
        "Huseinovic v. Lee Wilson Management, LLC, "
        "230\u00a0A.D.3d 576, 577 (1st Dep't 2024)."
    )

    candidates = extract_citation_candidates(source)

    assert len(candidates) == 1
    assert candidates[0].citation_type == "FullCaseCitation"
    assert candidates[0].text == "230\u00a0A.D.3d 576"
    assert candidates[0].normalized_text == "230 A.D.3d 576"
    assert source[candidates[0].start : candidates[0].end] == candidates[0].text


def test_recovers_complete_case_name_after_reliable_text_boundary() -> None:
    source = (
        "The agreement reaches later claims.  "
        "McMahan & Co. v. Bass, 250 A.D.2d 460, 461 (1st Dep't 1998); "
        "Shanghai Pearls & Gems, Inc. v. Paul, "
        "239 A.D.3d 31, 35-37 (1st Dep't 2025)."
    )

    candidates = extract_citation_candidates(source)

    assert [candidate.case_name for candidate in candidates] == [
        "McMahan & Co. v. Bass",
        "Shanghai Pearls & Gems, Inc. v. Paul",
    ]


def test_does_not_absorb_argument_text_into_complete_case_name() -> None:
    source = (
        "The records qualify.  Judicial records and contracts are undeniable. "
        "Phillips v. Taco Bell Corp., 152 A.D.3d 806, 807 (2d Dep't 2017).  "
        "There is no conflict. Uygur v. Superior Walls of Hudson Valley, Inc., "
        "35 A.D.3d 447, 448 (2d Dep't 2006)."
    )

    candidates = extract_citation_candidates(source)

    assert [candidate.case_name for candidate in candidates] == [
        "Phillips v. Taco Bell Corp.",
        "Uygur v. Superior Walls of Hudson Valley, Inc.",
    ]


def test_uses_each_cases_immediate_parenthetical_year() -> None:
    source = (
        "The cap controls.  Synthetic Systems, Inc. v. Example Corp., "
        "84\u00a0N.Y.2d 430, 436-39 (1994); "
        "Example v. Case, 104 A.D.3d 903, 905 (2d Dep't 2013)."
    )

    candidates = extract_citation_candidates(source)

    assert [dict(candidate.groups)["year"] for candidate in candidates] == [
        "1994",
        "2013",
    ]


def test_inherits_case_name_for_immediately_cited_affirmance() -> None:
    source = (
        "Paulino v. Braun, 2018 N.Y. Slip Op. 50896(U), at *2-3 "
        "(Sup. Ct. Bronx Cty. 2018), aff\u2019d, "
        "170 A.D.3d 506 (1st Dep't 2019)."
    )

    candidates = extract_citation_candidates(source)

    assert [candidate.case_name for candidate in candidates] == [
        "Paulino v. Braun",
        "Paulino v. Braun",
    ]
    assert candidates[1].toa_display == (
        "Paulino v. Braun, 170 A.D.3d 506 (1st Dep't 2019)"
    )


def test_keeps_placeholder_reporter_roman_in_slip_op_toa_display() -> None:
    source = (
        "The new decision controls.  Aretakis v. Sheehan, ___A.D.3d___, "
        "2026 NY Slip Op 03773 (2d Dep't June 17, 2026)."
    )

    candidates = extract_citation_candidates(source)

    assert len(candidates) == 1
    assert candidates[0].case_name == "Aretakis v. Sheehan"
    assert candidates[0].toa_display == (
        "Aretakis v. Sheehan, ___A.D.3d___, "
        "2026 NY Slip Op 03773 (2d Dep't June 17, 2026)"
    )


def test_extracts_constitutions_and_common_secondary_authorities() -> None:
    candidates = extract_citation_candidates(
        "U.S. Const. amend. XIV; N.Y. Const. art. I, § 6; "
        "Restatement (Second) of Contracts § 90; "
        "5 Wright & Miller, Federal Practice and Procedure § 1216."
    )

    assert [(item.category, item.normalized_text) for item in candidates] == [
        ("constitutional-provisions", "U.S. Const. amend. XIV"),
        ("constitutional-provisions", "N.Y. Const. art. I, § 6"),
        ("treatises", "Restatement (Second) of Contracts § 90"),
        ("treatises", "5 Wright & Miller, Federal Practice and Procedure § 1216"),
    ]


def test_inspects_synthetic_blank_word_template(tmp_path: Path) -> None:
    path = tmp_path / "blank.docx"
    document = Document()
    document.add_heading("Synthetic template", level=1)
    document.save(path)

    result = inspect_word_template(path)

    assert result.size_bytes > 0
    assert result.section_count == 1
    assert "Heading 1" in result.style_names
    assert len(result.sha256) == 64


def test_rejects_non_word_template(tmp_path: Path) -> None:
    path = tmp_path / "not-a-template.docx"
    path.write_text("not OOXML", encoding="utf-8")
    with pytest.raises(WordTemplateError, match="readable OOXML"):
        inspect_word_template(path)
