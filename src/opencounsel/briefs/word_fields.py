from __future__ import annotations

from dataclasses import dataclass

from lxml import etree

from opencounsel.briefs.docx import W_NS
from opencounsel.briefs.ooxml import XML_SPACE

DEFAULT_CASE_SOFT_BREAK_THRESHOLD = 90


@dataclass(frozen=True, slots=True)
class _TextChunk:
    text: str
    italic: bool = False


def ta_field_runs(
    long_form: str,
    short_form: str,
    category: int,
    *,
    italic_spans: tuple[tuple[int, int], ...] = (),
    case_soft_break_threshold: int | None = DEFAULT_CASE_SOFT_BREAK_THRESHOLD,
) -> tuple[etree._Element, ...]:
    """Return native TA field runs with semantic category and case-name italics."""
    if not long_form or not short_form:
        raise ValueError("TA field values must not be empty")
    if not 1 <= category <= 16:
        raise ValueError("TA field category must be between 1 and 16")
    chunks = _long_form_chunks(
        long_form,
        italic_spans,
        category=category,
        case_soft_break_threshold=case_soft_break_threshold,
    )
    runs = [_field_char_run("begin"), _instruction_run(' TA \\l "')]
    runs.extend(
        _instruction_run(chunk.text.replace('"', '""'), italic=chunk.italic)
        for chunk in chunks
        if chunk.text
    )
    runs.extend(
        (
            _instruction_run('" \\s "'),
            _instruction_run(short_form.replace('"', '""')),
            _instruction_run(f'" \\c {category} '),
            _field_char_run("end"),
        )
    )
    return tuple(runs)


def tc_field_runs(
    text: str,
    level: int,
    *,
    identifier: str = "O",
) -> tuple[etree._Element, ...]:
    """Return one page-free TC marker for a semantic heading."""
    if not text:
        raise ValueError("TC field text must not be empty")
    if not 1 <= level <= 9:
        raise ValueError("TC field level must be between 1 and 9")
    _require_identifier(identifier)
    instruction = (
        f' TC "{text.replace(chr(34), chr(34) * 2)}" '
        f'\\f {identifier} \\l "{level}" '
    )
    return (
        _field_char_run("begin"),
        _instruction_run(instruction),
        _field_char_run("end"),
    )


def toc_field_runs(
    result_text: str,
    *,
    identifier: str = "O",
) -> tuple[etree._Element, ...]:
    """Return a TOC field that compiles only OpenCounsel's TC markers."""
    _require_identifier(identifier)
    return _display_field_runs(f" TOC \\f {identifier} \\h \\z ", result_text)


def toa_field_runs(
    result_text: str,
    *,
    category: int | None = None,
) -> tuple[etree._Element, ...]:
    """Return a native TOA field, optionally restricted to one semantic category."""
    if category is not None and not 1 <= category <= 16:
        raise ValueError("TOA field category must be between 1 and 16")
    category_switch = f" \\c {category}" if category is not None else ""
    return _display_field_runs(f" TOA \\h \\p{category_switch} ", result_text)


def _display_field_runs(instruction: str, result_text: str) -> tuple[etree._Element, ...]:
    return (
        _field_char_run("begin", dirty=True),
        _instruction_run(instruction),
        _field_char_run("separate"),
        _text_run(result_text),
        _field_char_run("end"),
    )


def _field_char_run(kind: str, *, dirty: bool = False) -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    field = etree.SubElement(run, f"{{{W_NS}}}fldChar")
    field.set(f"{{{W_NS}}}fldCharType", kind)
    if dirty:
        field.set(f"{{{W_NS}}}dirty", "true")
    return run


def _instruction_run(text: str, *, italic: bool = False) -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    if italic:
        properties = etree.SubElement(run, f"{{{W_NS}}}rPr")
        etree.SubElement(properties, f"{{{W_NS}}}i")
        etree.SubElement(properties, f"{{{W_NS}}}iCs")
    instruction = etree.SubElement(run, f"{{{W_NS}}}instrText")
    instruction.text = text
    if text[:1].isspace() or text[-1:].isspace() or "\n" in text:
        instruction.set(XML_SPACE, "preserve")
    return run


def _text_run(text: str) -> etree._Element:
    run = etree.Element(f"{{{W_NS}}}r")
    value = etree.SubElement(run, f"{{{W_NS}}}t")
    value.text = text
    if text[:1].isspace() or text[-1:].isspace():
        value.set(XML_SPACE, "preserve")
    return run


def _long_form_chunks(
    long_form: str,
    italic_spans: tuple[tuple[int, int], ...],
    *,
    category: int,
    case_soft_break_threshold: int | None,
) -> tuple[_TextChunk, ...]:
    spans = _normalized_spans(italic_spans, len(long_form))
    chunks: list[_TextChunk] = []
    cursor = 0
    for start, end in spans:
        if cursor < start:
            chunks.append(_TextChunk(long_form[cursor:start]))
        chunks.append(_TextChunk(long_form[start:end], italic=True))
        cursor = end
    if cursor < len(long_form):
        chunks.append(_TextChunk(long_form[cursor:]))
    if not chunks:
        chunks.append(_TextChunk(long_form))

    break_at = _soft_break_position(
        long_form,
        spans,
        category,
        case_soft_break_threshold,
    )
    if break_at is None:
        return tuple(chunks)

    output: list[_TextChunk] = []
    cursor = 0
    inserted = False
    for chunk in chunks:
        end = cursor + len(chunk.text)
        if not inserted and cursor <= break_at <= end:
            local = break_at - cursor
            if before := chunk.text[:local]:
                output.append(_TextChunk(before, chunk.italic))
            output.append(_TextChunk("\n"))
            if after := chunk.text[local:]:
                output.append(_TextChunk(after, chunk.italic))
            inserted = True
        else:
            output.append(chunk)
        cursor = end
    return tuple(output)


def _normalized_spans(
    spans: tuple[tuple[int, int], ...], text_length: int
) -> tuple[tuple[int, int], ...]:
    normalized = sorted(
        (max(0, start), min(text_length, end))
        for start, end in spans
        if max(0, start) < min(text_length, end)
    )
    merged: list[tuple[int, int]] = []
    for start, end in normalized:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return tuple(merged)


def _soft_break_position(
    text: str,
    italic_spans: tuple[tuple[int, int], ...],
    category: int,
    threshold: int | None,
) -> int | None:
    if category != 1 or threshold is None or len(text) < threshold or not italic_spans:
        return None
    comma = text.find(",", max(end for _, end in italic_spans))
    if comma < 0:
        return None
    position = comma + 1
    while position < len(text) and text[position] == " ":
        position += 1
    if position >= len(text) or "\n" in text[comma : position + 1]:
        return None
    return position


def _require_identifier(identifier: str) -> None:
    if len(identifier) != 1 or not identifier.isascii() or not identifier.isalpha():
        raise ValueError("Word TC field identifier must be one ASCII letter")


__all__ = [
    "DEFAULT_CASE_SOFT_BREAK_THRESHOLD",
    "ta_field_runs",
    "tc_field_runs",
    "toa_field_runs",
    "toc_field_runs",
]
