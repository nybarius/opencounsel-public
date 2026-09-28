from __future__ import annotations

from lxml import etree

from opencounsel.briefs.docx import NS
from opencounsel.briefs.word_fields import ta_field_runs, toa_field_runs


def _instructions(runs: tuple[etree._Element, ...]) -> str:
    return "".join(
        str(value)
        for run in runs
        for value in run.xpath("./w:instrText/text()", namespaces=NS)
    )


def test_toa_fields_can_be_generated_per_semantic_category() -> None:
    assert _instructions(toa_field_runs("[CASES]", category=1)) == (
        " TOA \\h \\p \\c 1 "
    )
    assert _instructions(toa_field_runs("[STATUTES]", category=2)) == (
        " TOA \\h \\p \\c 2 "
    )
    assert _instructions(toa_field_runs("[RULES]", category=4)) == (
        " TOA \\h \\p \\c 4 "
    )
    assert _instructions(toa_field_runs("[REGULATIONS]", category=6)) == (
        " TOA \\h \\p \\c 6 "
    )


def test_case_ta_marker_italicizes_only_name_and_uses_pin_free_long_form() -> None:
    case_name = "Example Corp. v. Defendant LLC"
    citation = f"{case_name}, 123 F.4th 456 (2d Cir. 2026)"
    runs = ta_field_runs(
        citation,
        "Defendant",
        1,
        italic_spans=((0, len(case_name)),),
        case_soft_break_threshold=None,
    )
    instruction = _instructions(runs)
    assert instruction == (
        ' TA \\l "Example Corp. v. Defendant LLC, 123 F.4th 456 '
        '(2d Cir. 2026)" \\s "Defendant" \\c 1 '
    )
    assert "See " not in instruction
    assert ", 470" not in instruction
    italic_text = "".join(
        run.xpath("./w:instrText/text()", namespaces=NS)[0]
        for run in runs
        if run.xpath("./w:rPr/w:i", namespaces=NS)
    )
    assert italic_text == case_name
