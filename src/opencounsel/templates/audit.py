from __future__ import annotations

import json
import zipfile
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, cast

from docx import Document
from docx.document import Document as WordDocument
from docx.oxml.ns import qn
from docx.oxml.text.paragraph import CT_P
from docx.oxml.text.run import CT_R
from docx.shared import Length
from docx.styles.style import BaseStyle, ParagraphStyle
from docx.text.paragraph import Paragraph
from lxml import etree

from opencounsel.briefs.docx import inspect_brief_docx
from opencounsel.templates.build import BODY_STYLE, FOOTNOTE_STYLE, HEADING_STYLES
from opencounsel.templates.profiles import FilingProfile

Severity = Literal["info", "warning", "error"]

SERIF_FONTS = {
    "book antiqua", "bookman old style", "cambria", "century schoolbook",
    "constantia", "garamond", "georgia", "times new roman",
}
MONOSPACED_FONTS = {"courier", "courier new", "liberation mono"}
NUMBERED_HEADING_STYLES = {name for name, _, _ in HEADING_STYLES}


@dataclass(frozen=True, slots=True)
class StyleAuditFinding:
    code: str
    severity: Severity
    count: int
    scope: str


@dataclass(frozen=True, slots=True)
class WordStyleAudit:
    schema_version: int
    document_sha256: str
    profile_id: str
    paragraph_count: int
    style_counts: dict[str, int]
    findings: tuple[StyleAuditFinding, ...]


def audit_word_styles(path: Path, profile: FilingProfile) -> WordStyleAudit:
    inspection = inspect_brief_docx(path)
    document = Document(str(path))
    paragraphs = document.paragraphs
    findings: list[StyleAuditFinding] = []
    style_counts = Counter(
        paragraph.style.name if paragraph.style is not None else "Unstyled"
        for paragraph in paragraphs
    )

    _append_finding(
        findings,
        sum(
            len(paragraph._p.xpath(".//w:tab"))
            for paragraph in paragraphs
            if not _allows_table_tabs(paragraph)
        ),
        "manual-tab", "warning", "body",
    )
    _append_finding(
        findings,
        sum(
            len(paragraph._p.xpath('.//w:br[not(@w:type) or @w:type="textWrapping"] | .//w:cr'))
            for paragraph in paragraphs
            if _is_heading(paragraph.style)
        ),
        "manual-line-break-in-heading", "error", "headings",
    )
    _append_finding(
        findings,
        sum(len(paragraph._p.xpath('.//w:br[@w:type="page"]')) for paragraph in paragraphs),
        "manual-page-break", "warning", "body",
    )

    blank_paragraphs = sum(not paragraph.text.strip() for paragraph in paragraphs)
    if len(paragraphs) == 1 and blank_paragraphs == 1:
        blank_paragraphs = 0
    _append_finding(findings, blank_paragraphs, "blank-spacer-paragraph", "warning", "body")
    _append_finding(
        findings,
        sum(_has_direct_paragraph_formatting(p._p) for p in paragraphs),
        "direct-paragraph-formatting", "warning", "body",
    )
    _append_finding(
        findings,
        sum(
            _has_direct_run_formatting(run._r)
            for paragraph in paragraphs
            for run in paragraph.runs
        ),
        "direct-run-formatting", "warning", "body",
    )

    body_style = _body_style(document)
    body_font_name = cast(str | None, _effective_style_value(body_style, "font", "name"))
    body_font_size = cast(Length | None, _effective_style_value(body_style, "font", "size"))
    line_spacing = cast(
        float | Length | None,
        _effective_style_value(body_style, "paragraph_format", "line_spacing"),
    )
    if body_font_size is None or body_font_size.pt < profile.typography.body_min_pt:
        findings.append(StyleAuditFinding("body-font-too-small", "error", 1, "body-style"))
    if _font_kind(body_font_name) not in profile.typography.allowed_font_kinds:
        findings.append(StyleAuditFinding("body-font-kind-not-allowed", "error", 1, "body-style"))
    if line_spacing != 2.0:
        findings.append(StyleAuditFinding("body-not-double-spaced", "error", 1, "body-style"))

    footnote_style = _optional_style(document, FOOTNOTE_STYLE, "Footnote Text")
    if footnote_style is not None:
        footnote_size = cast(Length | None, _effective_style_value(footnote_style, "font", "size"))
        if footnote_size is None or footnote_size.pt < profile.typography.footnote_min_pt:
            findings.append(StyleAuditFinding("footnote-font-too-small", "error", 1, "footnote-style"))

    _append_finding(
        findings,
        sum(
            margin is None or margin.inches < profile.page.min_margin_in
            for section in document.sections
            for margin in (
                section.top_margin, section.right_margin,
                section.bottom_margin, section.left_margin,
            )
        ),
        "margin-too-small", "error", "sections",
    )
    _append_finding(
        findings,
        sum(
            _is_named_semantic_heading(style) and _outline_value(style) is None
            for style in document.styles
            if style.type == 1
        ),
        "heading-missing-outline-level", "error", "styles",
    )

    heading_num_ids = {
        value
        for style in document.styles
        if style.type == 1 and _is_numbered_heading(style)
        if (value := _style_num_id(style)) is not None
    }
    if len(heading_num_ids) > 1:
        findings.append(StyleAuditFinding("split-heading-numbering", "warning", len(heading_num_ids), "styles"))

    _append_finding(findings, _metadata_field_count(document), "metadata-present", "warning", "core-properties")
    if _theme_font_mismatch(path, body_font_name):
        findings.append(StyleAuditFinding("theme-font-mismatch", "warning", 1, "theme"))

    findings.sort(key=lambda item: (item.severity, item.code, item.scope))
    return WordStyleAudit(
        schema_version=1,
        document_sha256=inspection.sha256,
        profile_id=profile.profile_id,
        paragraph_count=len(paragraphs),
        style_counts=dict(sorted(style_counts.items())),
        findings=tuple(findings),
    )


def write_style_audit(report: WordStyleAudit, output: Path) -> Path:
    if output.suffix.lower() != ".json" or output.is_symlink():
        raise ValueError("style audit output must be a regular JSON path")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(asdict(report), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    output.chmod(0o600)
    return output


def _append_finding(
    findings: list[StyleAuditFinding], count: int, code: str, severity: Severity, scope: str
) -> None:
    if count:
        findings.append(StyleAuditFinding(code, severity, count, scope))


def _has_direct_paragraph_formatting(element: CT_P) -> bool:
    p_pr = element.find(qn("w:pPr"))
    if p_pr is None:
        return False
    ignored = {qn("w:pStyle"), qn("w:sectPr")}
    return any(child.tag not in ignored for child in p_pr)


def _has_direct_run_formatting(element: CT_R) -> bool:
    r_pr = element.find(qn("w:rPr"))
    return r_pr is not None and any(child.tag != qn("w:rStyle") for child in r_pr)


def _allows_table_tabs(paragraph: Paragraph) -> bool:
    style_name = paragraph.style.name if paragraph.style is not None else ""
    return style_name.startswith("TOC ") or style_name == "Table of Authorities"


def _is_heading(style: BaseStyle | None) -> bool:
    return _is_named_semantic_heading(style) or _outline_value(style) not in {None, 9}


def _is_named_semantic_heading(style: BaseStyle | None) -> bool:
    name = str(getattr(style, "name", "")).lower()
    return "heading" in name and not name.startswith("toc")


def _is_numbered_heading(style: BaseStyle | None) -> bool:
    return str(getattr(style, "name", "")) in NUMBERED_HEADING_STYLES


def _outline_value(style: BaseStyle | None) -> int | None:
    if style is None:
        return None
    p_pr = style.element.find(qn("w:pPr"))
    if p_pr is None or (outline := p_pr.find(qn("w:outlineLvl"))) is None:
        return None
    try:
        return int(outline.get(qn("w:val")))
    except (TypeError, ValueError):
        return None


def _style_num_id(style: BaseStyle) -> str | None:
    p_pr = style.element.find(qn("w:pPr"))
    if p_pr is None:
        return None
    num_id = p_pr.find(f"{qn('w:numPr')}/{qn('w:numId')}")
    return num_id.get(qn("w:val")) if num_id is not None else None


def _body_style(document: WordDocument) -> ParagraphStyle:
    return cast(ParagraphStyle, _optional_style(document, BODY_STYLE) or document.styles["Normal"])


def _optional_style(document: WordDocument, *names: str) -> ParagraphStyle | None:
    for name in names:
        try:
            return cast(ParagraphStyle, document.styles[name])
        except KeyError:
            pass
    return None


def _effective_style_value(style: ParagraphStyle, component: str, attribute: str) -> object:
    current: ParagraphStyle | None = style
    while current is not None:
        value = getattr(getattr(current, component), attribute)
        if value is not None:
            return value
        current = cast(ParagraphStyle | None, current.base_style)
    return None


def _font_kind(font_name: object) -> str | None:
    if not isinstance(font_name, str):
        return None
    normalized = font_name.casefold()
    if normalized in SERIF_FONTS:
        return "proportional-serif"
    if normalized in MONOSPACED_FONTS:
        return "monospace"
    return None


def _metadata_field_count(document: WordDocument) -> int:
    properties = document.core_properties
    return sum(
        bool(value)
        for value in (
            properties.author, properties.last_modified_by, properties.title,
            properties.subject, properties.keywords, properties.comments, properties.category,
        )
    )


def _theme_font_mismatch(path: Path, body_font_name: str | None) -> bool:
    if body_font_name is None:
        return False
    with zipfile.ZipFile(path) as archive:
        try:
            root = etree.fromstring(archive.read("word/theme/theme1.xml"))
        except KeyError:
            return False
    values = cast(
        list[str],
        root.xpath(
            ".//a:fontScheme/a:majorFont/a:latin/@typeface | "
            ".//a:fontScheme/a:minorFont/a:latin/@typeface",
            namespaces={"a": "http://schemas.openxmlformats.org/drawingml/2006/main"},
        ),
    )
    return any(value and value.casefold() != body_font_name.casefold() for value in values)


__all__ = ["StyleAuditFinding", "WordStyleAudit", "audit_word_styles", "write_style_audit"]
