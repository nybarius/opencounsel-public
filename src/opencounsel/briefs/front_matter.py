from __future__ import annotations

import hashlib
import json
import re

from opencounsel.briefs.ir import AuthorityOccurrence, BriefAudit
from opencounsel.contracts.models import (
    FrontMatterCategory,
    FrontMatterLocation,
    FrontMatterSource,
    ToaSourceEntry,
    TocSourceEntry,
)

_CATEGORY: dict[str, tuple[FrontMatterCategory, int, str]] = {
    "cases": ("cases", 1, "Cases"),
    "laws": ("statutes", 2, "Statutes"),
    "statutes": ("statutes", 2, "Statutes"),
    "other-authorities": ("other-authorities", 3, "Other Authorities"),
    "rules": ("rules", 4, "Rules"),
    "treatises": ("treatises", 5, "Treatises"),
    "regulations": ("regulations", 6, "Regulations"),
    "constitutional-provisions": (
        "constitutional-provisions",
        7,
        "Constitutional Provisions",
    ),
}


def build_front_matter_source(audit: BriefAudit) -> FrontMatterSource:
    """Compile page-free semantic TOC and canonical TOA records from one audit."""
    number_labels = _toc_number_labels(audit)
    toc = tuple(
        TocSourceEntry(
            entry_id=_stable_id(
                "fm-toc",
                {
                    "part": heading.part,
                    "paragraph_index": heading.paragraph_index,
                    "level": heading.level,
                    "heading": heading.text,
                    "number_label": number_label,
                },
            ),
            level=heading.level,
            heading=heading.text,
            number_label=number_label,
            part="document",
            paragraph_index=heading.paragraph_index,
            style_id=heading.style_id,
            basis=heading.basis,
        )
        for heading, number_label in zip(
            audit.headings, number_labels, strict=True
        )
    )

    canonical: dict[str, list[AuthorityOccurrence]] = {}
    for authority in audit.authorities:
        if authority.is_canonical_candidate:
            canonical.setdefault(authority.normalized_text.casefold(), []).append(authority)

    grouped: dict[str, list[AuthorityOccurrence]] = {}
    excluded = 0
    for authority in audit.authorities:
        key = (authority.resolved_citation or authority.normalized_text).casefold()
        if key not in canonical:
            excluded += 1
            continue
        grouped.setdefault(key, []).append(authority)

    toa: list[ToaSourceEntry] = []
    for key, occurrences in grouped.items():
        sources = canonical[key]
        first = sources[0]
        category, word_category, heading = _category(first)
        display_name = _display_name(first)
        short_name = _short_name(first, occurrences)
        case_name = first.case_name or ""
        italic_spans = (
            ((0, len(case_name)),)
            if category == "cases" and case_name and display_name.startswith(case_name)
            else ()
        )
        locations = tuple(
            FrontMatterLocation(
                part=occurrence.part,
                paragraph_index=occurrence.paragraph_index,
                start_offset=occurrence.start,
                end_offset=occurrence.end,
                original_text=occurrence.text,
                citation_type=occurrence.citation_type,
            )
            for occurrence in occurrences
        )
        targets = tuple(
            sorted(
                {
                    occurrence.hyperlink_target
                    for occurrence in occurrences
                    if occurrence.hyperlink_target
                }
            )
        )
        normalized = first.normalized_text.rstrip(".,;:")
        toa.append(
            ToaSourceEntry(
                authority_id=_stable_id(
                    "fm-toa",
                    {"category": category, "normalized_citation": normalized.casefold()},
                ),
                category=category,
                word_category=word_category,
                category_heading=heading,
                display_name=display_name.rstrip(".,;:"),
                short_name=short_name,
                normalized_citation=normalized,
                italic_spans=italic_spans,
                locations=locations,
                existing_targets=targets,
            )
        )
    toa.sort(
        key=lambda entry: (
            entry.word_category,
            entry.display_name.casefold(),
            entry.normalized_citation.casefold(),
        )
    )
    return FrontMatterSource(
        brief_sha256=audit.brief_sha256,
        toc=toc,
        toa=tuple(toa),
        excluded_authority_occurrence_count=excluded,
    )


def _toc_number_labels(audit: BriefAudit) -> tuple[str | None, ...]:
    counters = [0, 0, 0, 0]
    labels: list[str | None] = []
    for heading in audit.headings:
        match = re.fullmatch(
            r"_?LegalHeadingNum([1-4])",
            heading.style_id or "",
            re.IGNORECASE,
        )
        if match is None:
            labels.append(None)
            continue
        level = int(match.group(1)) - 1
        counters[level] += 1
        counters[level + 1 :] = [0] * (len(counters) - level - 1)
        value = counters[level]
        if level == 0:
            label = _roman(value)
        elif level == 1:
            label = _letters(value).upper()
        elif level == 2:
            label = str(value)
        else:
            label = _letters(value).lower()
        labels.append(f"{label}.")
    return tuple(labels)


def _letters(value: int) -> str:
    output = ""
    while value:
        value, remainder = divmod(value - 1, 26)
        output = chr(ord("A") + remainder) + output
    return output


def _roman(value: int) -> str:
    numerals = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    output = ""
    for number, numeral in numerals:
        count, value = divmod(value, number)
        output += numeral * count
    return output


def _category(authority: AuthorityOccurrence) -> tuple[FrontMatterCategory, int, str]:
    groups = dict(authority.groups)
    if groups.get("ruleset") == "nycrr":
        return _CATEGORY["regulations"]
    return _CATEGORY.get(authority.category, _CATEGORY["other-authorities"])


def _display_name(authority: AuthorityOccurrence) -> str:
    if authority.toa_display:
        return " ".join(authority.toa_display.split())
    if authority.case_name:
        return f"{authority.case_name}, {authority.normalized_text}"
    return authority.normalized_text


def _short_name(
    canonical: AuthorityOccurrence,
    occurrences: list[AuthorityOccurrence],
) -> str:
    aliases = [
        occurrence.case_name
        for occurrence in occurrences
        if not occurrence.is_canonical_candidate and occurrence.case_name
    ]
    if aliases:
        return min(aliases, key=lambda value: (len(value), value.casefold()))
    name = canonical.case_name
    if not name:
        return canonical.normalized_text
    if " v. " in name:
        defendant = name.rsplit(" v. ", maxsplit=1)[1]
        cleaned = re.sub(r",?\s+(?:Inc\.?|LLC|L\.P\.|Corp\.?|Ltd\.?)$", "", defendant)
        return cleaned.strip() or name
    return name


def _stable_id(prefix: str, value: dict[str, object]) -> str:
    body = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return f"{prefix}-{hashlib.sha256(body).hexdigest()}"


__all__ = [
    "FrontMatterLocation",
    "FrontMatterSource",
    "ToaSourceEntry",
    "TocSourceEntry",
    "build_front_matter_source",
]
