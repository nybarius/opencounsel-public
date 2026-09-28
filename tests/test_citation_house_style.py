from __future__ import annotations

from opencounsel.briefs.citation_house_style import citation_house_style_findings


def test_house_style_removes_internal_external_qualifiers() -> None:
    text = (
        "(internal quotation marks and citations omitted); "
        "(external citation omitted); (internal quotations omitted)"
    )
    findings = citation_house_style_findings(text)

    assert [(finding.phrase, finding.preferred) for finding in findings] == [
        (
            "internal quotation marks and citations omitted",
            "quotation and citations omitted",
        ),
        ("external citation omitted", "citation omitted"),
        ("internal quotations omitted", "quotations omitted"),
    ]


def test_preferred_house_forms_are_not_flagged() -> None:
    assert not citation_house_style_findings(
        "(citation omitted); (citations omitted); (quotation and citation omitted)"
    )
