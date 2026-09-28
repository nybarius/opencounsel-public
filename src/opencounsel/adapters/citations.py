from __future__ import annotations

import re
from dataclasses import dataclass, replace

from eyecite import get_citations


@dataclass(frozen=True, slots=True)
class CitationCandidate:
    text: str
    normalized_text: str
    case_name: str | None
    start: int
    end: int
    citation_type: str
    category: str
    groups: tuple[tuple[str, str], ...] = ()
    toa_display: str | None = None

    @property
    def is_canonical_candidate(self) -> bool:
        return self.citation_type in {
            "ConstitutionCitation",
            "FullCaseCitation",
            "FullLawCitation",
            "SecondaryAuthorityCitation",
            "StateLawCitation",
            "VendorCaseCitation",
            "RuleCitation",
        }


@dataclass(frozen=True, slots=True)
class _DetectorCandidate:
    candidate: CitationCandidate
    priority: int


_SECTION_TOKEN = re.compile(
    r"[0-9][0-9A-Za-z]*(?:[.\-][0-9A-Za-z]+)*(?:\([0-9A-Za-z\-]+\))*"
)
_SECTION_SEPARATOR = re.compile(r"\s*(?:,|\band\b|&)\s*", re.IGNORECASE)
_FEDERAL_PREFIX = re.compile(
    r"(?<![A-Za-z0-9])(?P<title>\d+)\s+"
    r"(?P<reporter>U\.?\s*S\.?\s*C\.?|C\.?\s*F\.?\s*R\.?)\s*"
    r"(?P<symbol>§{1,2}|sections?)\s*",
    re.IGNORECASE,
)
_VENDOR_CASE = re.compile(
    r"(?<![A-Za-z0-9])\d{4}\s+"
    r"(?:N\.?\s*Y\.?|U\.?\s*S\.?)(?:\s+[A-Za-z][A-Za-z.]*){0,4}\s+"
    r"(?:LEXIS|WL)\s+\d+(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_PLACEHOLDER_REPORTER_PATTERN = (
    r"_{2,}\s*(?:[A-Za-z]\.?)"
    r"{1,6}\s*\d+[A-Za-z]?\s*_{2,}"
)
_TRAILING_PLACEHOLDER_REPORTER = re.compile(
    rf",\s*{_PLACEHOLDER_REPORTER_PATTERN}\s*$",
    re.IGNORECASE,
)
_PRECEDING_PLACEHOLDER_REPORTER = re.compile(
    rf",\s*(?P<reporter>{_PLACEHOLDER_REPORTER_PATTERN})\s*,?\s*$",
    re.IGNORECASE,
)
_FEDERAL_RULES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "frcp",
        "Fed. R. Civ. P.",
        (r"Fed(?:eral)?\.?\s+R(?:ule)?s?\.?\s+(?:of\s+)?Civ(?:il)?\.?\s+P(?:rocedure)?\.?",),
    ),
    (
        "frap",
        "Fed. R. App. P.",
        (r"Fed(?:eral)?\.?\s+R(?:ule)?s?\.?\s+(?:of\s+)?App(?:ellate)?\.?\s+P(?:rocedure)?\.?",),
    ),
    (
        "fre",
        "Fed. R. Evid.",
        (r"Fed(?:eral)?\.?\s+R(?:ule)?s?\.?\s+(?:of\s+)?Evid(?:ence)?\.?",),
    ),
    (
        "frcrmp",
        "Fed. R. Crim. P.",
        (r"Fed(?:eral)?\.?\s+R(?:ule)?s?\.?\s+(?:of\s+)?Crim(?:inal)?\.?\s+P(?:rocedure)?\.?",),
    ),
    (
        "frbp",
        "Fed. R. Bankr. P.",
        (r"Fed(?:eral)?\.?\s+R(?:ule)?s?\.?\s+(?:of\s+)?Bankr(?:uptcy)?\.?\s+P(?:rocedure)?\.?",),
    ),
)
_NYCRR_PREFIX = re.compile(
    r"(?<![A-Za-z0-9])(?P<title>\d+)\s+N\.?\s*Y\.?\s*C\.?\s*R\.?\s*R\.?\s*"
    r"(?:§{1,2}\s*)?",
    re.IGNORECASE,
)
_CONSTITUTIONS: tuple[tuple[str, str, str], ...] = (
    ("us", "U.S. Const.", r"U\.?\s*S\.?\s+Const\.?"),
    ("ny", "N.Y. Const.", r"N\.?\s*Y\.?\s+Const\.?"),
)
_CONSTITUTION_PROVISION = re.compile(
    r"(?P<kind>art\.|article|amend\.|amendment)\s*"
    r"(?P<number>[IVXLCDM]+|\d+)"
    r"(?:\s*,?\s*§{1,2}\s*(?P<section>\d+[A-Za-z]*(?:\([A-Za-z0-9]+\))*))?"
    r"(?:\s*,?\s*cl\.?\s*(?P<clause>\d+))?",
    re.IGNORECASE,
)
_RESTATEMENT = re.compile(
    r"Restatement\s+\((?P<series>First|Second|Third|Fourth)\)\s+of\s+"
    r"(?P<subject>[A-Z][A-Za-z&'\- ]+?)\s+§{1,2}\s*"
    r"(?P<section>\d+[A-Za-z]*(?:\([A-Za-z0-9]+\))*)",
    re.IGNORECASE,
)
_WRIGHT_MILLER = re.compile(
    r"(?P<volume>\d+[A-Za-z]?)\s+Wright\s*&\s*Miller,\s+"
    r"Federal\s+Practice\s+and\s+Procedure\s+§{1,2}\s*"
    r"(?P<section>\d+[A-Za-z]*(?:\.\d+)?)",
    re.IGNORECASE,
)

# The code identifiers are the New York Senate Open Legislation identifiers.
_NY_CODES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("CVP", "CPLR", (r"CPLR", r"N\.?\s*Y\.?\s+C\.?\s*P\.?\s*L\.?\s*R\.?")),
    ("JUD", "Judiciary Law", (r"(?:N\.?\s*Y\.?\s+)?Judiciary\s+Law",)),
    (
        "GBS",
        "General Business Law",
        (r"(?:N\.?\s*Y\.?\s+)?Gen(?:eral)?\.?\s+Bus(?:iness)?\.?\s+Law",),
    ),
    (
        "GOB",
        "General Obligations Law",
        (r"(?:N\.?\s*Y\.?\s+)?Gen(?:eral)?\.?\s+Oblig(?:ations)?\.?\s+Law",),
    ),
    ("RPA", "RPAPL", (r"RPAPL", r"Real\s+Property\s+Actions\s+(?:and|&)\s+Proceedings\s+Law")),
    ("RPP", "Real Property Law", (r"(?:N\.?\s*Y\.?\s+)?Real\s+Property\s+Law", r"RPL")),
    (
        "DBT",
        "Debtor and Creditor Law",
        (r"(?:N\.?\s*Y\.?\s+)?Debtor\s+(?:and|&)\s+Creditor\s+Law", r"DCL"),
    ),
    ("EXC", "Executive Law", (r"(?:N\.?\s*Y\.?\s+)?Executive\s+Law",)),
    (
        "BSC",
        "Business Corporation Law",
        (r"(?:N\.?\s*Y\.?\s+)?Business\s+Corporation\s+Law", r"BCL"),
    ),
    (
        "LLC",
        "Limited Liability Company Law",
        (r"(?:N\.?\s*Y\.?\s+)?Limited\s+Liability\s+Company\s+Law", r"LLCL"),
    ),
)


def extract_citation_candidates(text: str) -> tuple[CitationCandidate, ...]:
    """Return non-overlapping local proposals without treating ambiguous short cites as law."""
    detected: list[_DetectorCandidate] = []
    # Legal drafts commonly keep reporter citations together with nonbreaking
    # spaces.  eyecite expects ordinary whitespace, so scan an equal-length
    # shadow string and retain the original source slices and offsets.
    scan_text = text.translate({ord("\u00a0"): " ", ord("\u202f"): " "})
    for citation in get_citations(scan_text):
        start, end = citation.span()
        citation_type = type(citation).__name__
        group_values = {
            str(key): str(value)
            for key, value in getattr(citation, "groups", {}).items()
            if value is not None
        }
        metadata = getattr(citation, "metadata", None)
        for name in ("court", "year"):
            value = getattr(metadata, name, None)
            if value is not None:
                group_values.setdefault(name, str(value))
        if citation_type == "FullCaseCitation" and (
            local_year := _immediate_case_year(text, end)
        ):
            group_values["year"] = local_year
        groups = tuple(sorted(group_values.items()))
        case_types = {"IdCitation", "SupraCitation"}
        category = "cases" if "Case" in citation_type or citation_type in case_types else "laws"
        metadata_case_name = _case_name(citation)
        source_case_name = _source_case_name(text, start)
        case_name = _clean_case_name(
            source_case_name
            if _should_recover_case_name(metadata_case_name, source_case_name)
            else metadata_case_name
        )
        normalized_text = citation.corrected_citation()
        detected.append(
            _DetectorCandidate(
                CitationCandidate(
                    text=text[start:end],
                    normalized_text=normalized_text,
                    case_name=case_name,
                    start=start,
                    end=end,
                    citation_type=citation_type,
                    category=category,
                    groups=groups,
                    toa_display=_case_toa_display(
                        text,
                        start,
                        end,
                        case_name,
                        normalized_text,
                    )
                    if citation_type == "FullCaseCitation"
                    else normalized_text,
                ),
                100 if citation_type.startswith("Full") else 20,
            )
        )

    detected.extend(_federal_section_candidates(text))
    detected.extend(_new_york_section_candidates(text))
    detected.extend(_rule_candidates(text))
    detected.extend(_constitution_candidates(text))
    detected.extend(_secondary_authority_candidates(text))
    for match in _VENDOR_CASE.finditer(text):
        vendor_citation = " ".join(match.group(0).split())
        pieces = vendor_citation.split()
        reporter = " ".join(pieces[1:-1])
        detected.append(
            _DetectorCandidate(
                CitationCandidate(
                    text=match.group(0),
                    normalized_text=vendor_citation,
                    case_name=_clean_case_name(
                        _preceding_case_name(text, match.start())
                    ),
                    start=match.start(),
                    end=match.end(),
                    citation_type="VendorCaseCitation",
                    category="cases",
                    groups=(
                        ("page", pieces[-1]),
                        ("reporter", reporter),
                        ("volume", pieces[0]),
                        ("year", pieces[0]),
                    ),
                    toa_display=_case_toa_display(
                        text,
                        match.start(),
                        match.end(),
                        _clean_case_name(_preceding_case_name(text, match.start())),
                        vendor_citation,
                    ),
                ),
                110,
            )
        )
    selected = tuple(item.candidate for item in _maximum_weight_nonoverlap(detected))
    return _inherit_affirmance_case_names(text, selected)


def _preceding_case_name(text: str, start: int) -> str | None:
    prefix = text[max(0, start - 180) : start]
    match = re.search(
        r"(?P<name>(?:(?:In\s+re|Matter\s+of)\s+[^,;:.]{1,100}|"
        r"[A-Z][^,;:.]{0,80}\s+v\.?\s+[^,;:.]{1,80}))\s*,?\s*$",
        prefix,
    )
    return " ".join(match.group("name").split()) if match else None


def _source_case_name(text: str, start: int) -> str | None:
    """Recover a complete case name after a reliable sentence or cite boundary."""
    prefix = text[max(0, start - 300) : start]
    boundaries = tuple(
        match.end() for match in re.finditer(r"(?:;\s+|[.!?]\s{2,})", prefix)
    )
    if not boundaries:
        return None
    segment = prefix[boundaries[-1] :].strip(" \t\r\n(,")
    segment = re.sub(
        r"^(?:(?:accord|see(?:\s+also)?|but\s+see|cf\.?|contra|e\.g\.)\s*,?\s+)+",
        "",
        segment,
        flags=re.IGNORECASE,
    ).rstrip(" \t\r\n,")
    if not segment or len(segment) > 220:
        return None
    if " v. " not in segment and not re.match(r"^(?:In\s+re|Matter\s+of)\s+", segment):
        return None
    return " ".join(segment.split())


def _clean_case_name(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = _TRAILING_PLACEHOLDER_REPORTER.sub("", value).rstrip(" ,")
    return cleaned or None


def _should_recover_case_name(metadata_name: str | None, source_name: str | None) -> bool:
    if not metadata_name or not source_name or metadata_name == source_name:
        return False
    metadata_key = re.sub(r"[^a-z0-9]", "", metadata_name.casefold())
    source_key = re.sub(r"[^a-z0-9]", "", source_name.casefold())
    if metadata_name.startswith("Matter  ") and source_name.startswith("Matter of "):
        return True
    if not source_key.endswith(metadata_key):
        return False
    if " v. " not in metadata_name and " v. " in source_name:
        return True
    if " v. " not in metadata_name:
        return False
    plaintiff = metadata_name.split(" v. ", maxsplit=1)[0]
    return len(plaintiff.split()) <= 2 and bool(
        re.search(r"(?:^|[,& ]\s*)(?:Co\.|Corp\.|Inc\.|LLC|L\.P\.|Ltd\.)$", plaintiff)
    )


def _immediate_case_year(text: str, citation_end: int) -> str | None:
    parenthetical = _case_parenthetical(text, citation_end)
    if parenthetical is None:
        return None
    years = re.findall(r"\b(?:18|19|20)\d{2}\b", parenthetical)
    return years[-1] if years else None


def _inherit_affirmance_case_names(
    text: str, candidates: tuple[CitationCandidate, ...]
) -> tuple[CitationCandidate, ...]:
    """Give an immediately cited affirmance the lower decision's case name."""
    output: list[CitationCandidate] = []
    prior_full_case: CitationCandidate | None = None
    for candidate in candidates:
        updated = candidate
        if (
            candidate.citation_type == "FullCaseCitation"
            and candidate.case_name is None
            and prior_full_case is not None
            and prior_full_case.case_name
            and re.search(
                r"\baff[\u2019']d(?:\s+mem\.?)?\s*,?\s*$",
                text[prior_full_case.end : candidate.start],
                re.IGNORECASE,
            )
        ):
            updated = replace(
                candidate,
                case_name=prior_full_case.case_name,
                toa_display=_case_toa_display(
                    text,
                    candidate.start,
                    candidate.end,
                    prior_full_case.case_name,
                    candidate.normalized_text,
                ),
            )
        output.append(updated)
        if updated.citation_type == "FullCaseCitation":
            prior_full_case = updated
    return tuple(output)


def _case_parenthetical(text: str, citation_end: int) -> str | None:
    tail = text[citation_end : citation_end + 160]
    match = re.match(
        r"(?:,\s+(?:at\s+)?\*?\d+(?:[-\u2013\u2014]\d+)?)?\s*"
        r"(?P<parenthetical>\([^()\n]{0,120}\b\d{4}\))",
        tail,
    )
    return match.group("parenthetical") if match else None


def _case_toa_display(
    text: str,
    citation_start: int,
    citation_end: int,
    case_name: str | None,
    normalized_citation: str,
) -> str:
    """Build a pin-free TOA display form from one full citation occurrence."""
    parenthetical = _case_parenthetical(text, citation_end)
    suffix = f" {parenthetical}" if parenthetical else ""
    prefix = text[max(0, citation_start - 120) : citation_start]
    placeholder = _PRECEDING_PLACEHOLDER_REPORTER.search(prefix)
    reporter = f"{placeholder.group('reporter')}, " if placeholder else ""
    citation = f"{reporter}{normalized_citation}{suffix}"
    return f"{case_name}, {citation}" if case_name else citation


def _federal_section_candidates(text: str) -> list[_DetectorCandidate]:
    candidates: list[_DetectorCandidate] = []
    for match in _FEDERAL_PREFIX.finditer(text):
        title = match.group("title")
        reporter = re.sub(r"[\s.]", "", match.group("reporter")).upper()
        reporter = "U.S.C." if reporter == "USC" else "C.F.R."
        candidates.extend(
            _section_list(
                text,
                match.start(),
                match.end(),
                category="statutes" if reporter == "U.S.C." else "regulations",
                citation_type="FullLawCitation",
                label=f"{title} {reporter}",
                base_groups=(("title", title), ("reporter", reporter)),
                priority=120,
            )
        )
    return candidates


def _rule_candidates(text: str) -> list[_DetectorCandidate]:
    candidates: list[_DetectorCandidate] = []
    for ruleset, label, aliases in _FEDERAL_RULES:
        prefix = re.compile(
            rf"(?<![A-Za-z0-9])(?:{'|'.join(aliases)})\s*",
            re.IGNORECASE,
        )
        for match in prefix.finditer(text):
            rule = _SECTION_TOKEN.match(text, match.end())
            if rule is None:
                continue
            number = rule.group(0)
            candidates.append(
                _DetectorCandidate(
                    CitationCandidate(
                        text=text[match.start() : rule.end()],
                        normalized_text=f"{label} {number}",
                        case_name=None,
                        start=match.start(),
                        end=rule.end(),
                        citation_type="RuleCitation",
                        category="rules",
                        groups=(
                            ("jurisdiction", "federal"),
                            ("rule", number),
                            ("ruleset", ruleset),
                        ),
                    ),
                    125,
                )
            )
    for match in _NYCRR_PREFIX.finditer(text):
        section = _SECTION_TOKEN.match(text, match.end())
        if section is None:
            continue
        number = section.group(0)
        title = match.group("title")
        candidates.append(
            _DetectorCandidate(
                CitationCandidate(
                    text=text[match.start() : section.end()],
                    normalized_text=f"{title} N.Y.C.R.R. § {number}",
                    case_name=None,
                    start=match.start(),
                    end=section.end(),
                    citation_type="RuleCitation",
                    category="rules",
                    groups=(
                        ("jurisdiction", "ny"),
                        ("rule", number),
                        ("ruleset", "nycrr"),
                        ("title", title),
                    ),
                ),
                125,
            )
        )
    return candidates


def _constitution_candidates(text: str) -> list[_DetectorCandidate]:
    candidates: list[_DetectorCandidate] = []
    for jurisdiction, label, alias in _CONSTITUTIONS:
        prefix = re.compile(rf"(?<![A-Za-z0-9])(?:{alias})\s*", re.IGNORECASE)
        for match in prefix.finditer(text):
            provision = _CONSTITUTION_PROVISION.match(text, match.end())
            if provision is None:
                continue
            kind = provision.group("kind").casefold()
            kind = "art." if kind.startswith("art") else "amend."
            number = provision.group("number")
            if number.isalpha():
                number = number.upper()
            normalized = f"{label} {kind} {number}"
            groups: list[tuple[str, str]] = [
                ("jurisdiction", jurisdiction),
                ("provision", f"{kind} {number}"),
            ]
            if section := provision.group("section"):
                normalized += f", § {section}"
                groups.append(("section", section))
            if clause := provision.group("clause"):
                normalized += f", cl. {clause}"
                groups.append(("clause", clause))
            candidates.append(
                _DetectorCandidate(
                    CitationCandidate(
                        text=text[match.start() : provision.end()],
                        normalized_text=normalized,
                        case_name=None,
                        start=match.start(),
                        end=provision.end(),
                        citation_type="ConstitutionCitation",
                        category="constitutional-provisions",
                        groups=tuple(sorted(groups)),
                        toa_display=normalized,
                    ),
                    150,
                )
            )
    return candidates


def _secondary_authority_candidates(text: str) -> list[_DetectorCandidate]:
    candidates: list[_DetectorCandidate] = []
    for match in _RESTATEMENT.finditer(text):
        series = match.group("series").title()
        subject = " ".join(match.group("subject").split()).title()
        section = match.group("section")
        normalized = f"Restatement ({series}) of {subject} § {section}"
        candidates.append(
            _DetectorCandidate(
                CitationCandidate(
                    text=match.group(0),
                    normalized_text=normalized,
                    case_name=None,
                    start=match.start(),
                    end=match.end(),
                    citation_type="SecondaryAuthorityCitation",
                    category="treatises",
                    groups=(("kind", "restatement"), ("section", section)),
                    toa_display=normalized,
                ),
                150,
            )
        )
    for match in _WRIGHT_MILLER.finditer(text):
        volume = match.group("volume")
        section = match.group("section")
        normalized = (
            f"{volume} Wright & Miller, Federal Practice and Procedure § {section}"
        )
        candidates.append(
            _DetectorCandidate(
                CitationCandidate(
                    text=match.group(0),
                    normalized_text=normalized,
                    case_name=None,
                    start=match.start(),
                    end=match.end(),
                    citation_type="SecondaryAuthorityCitation",
                    category="treatises",
                    groups=(
                        ("kind", "wright-miller"),
                        ("section", section),
                        ("volume", volume),
                    ),
                    toa_display=normalized,
                ),
                150,
            )
        )
    return candidates


def _new_york_section_candidates(text: str) -> list[_DetectorCandidate]:
    candidates: list[_DetectorCandidate] = []
    for code, canonical_name, aliases in _NY_CODES:
        alias = "(?:" + "|".join(aliases) + ")"
        prefix = re.compile(
            rf"(?<![A-Za-z0-9])(?P<name>{alias})\s*(?:§{{1,2}}\s*)?",
            re.IGNORECASE,
        )
        for match in prefix.finditer(text):
            candidates.extend(
                _section_list(
                    text,
                    match.start(),
                    match.end(),
                    category="statutes",
                    citation_type="StateLawCitation",
                    label=canonical_name,
                    base_groups=(("jurisdiction", "ny"), ("code", code)),
                    priority=130,
                )
            )
    return candidates


def _section_list(
    text: str,
    prefix_start: int,
    cursor: int,
    *,
    category: str,
    citation_type: str,
    label: str,
    base_groups: tuple[tuple[str, str], ...],
    priority: int,
) -> list[_DetectorCandidate]:
    first = True
    candidates: list[_DetectorCandidate] = []
    while section_match := _SECTION_TOKEN.match(text, cursor):
        section = section_match.group(0)
        start = prefix_start if first else section_match.start()
        normalized = f"{label} § {section}"
        candidates.append(
            _DetectorCandidate(
                CitationCandidate(
                    text=text[start : section_match.end()],
                    normalized_text=normalized,
                    case_name=None,
                    start=start,
                    end=section_match.end(),
                    citation_type=citation_type,
                    category=category,
                    groups=tuple(sorted((*base_groups, ("section", section)))),
                ),
                priority,
            )
        )
        first = False
        separator = _SECTION_SEPARATOR.match(text, section_match.end())
        if separator is None:
            break
        cursor = separator.end()
    return candidates


def _maximum_weight_nonoverlap(
    detected: list[_DetectorCandidate],
) -> list[_DetectorCandidate]:
    """Select the globally best non-overlapping detector output, independent of detector order."""
    if not detected:
        return []
    items = sorted(detected, key=lambda item: (item.candidate.end, item.candidate.start))
    previous: list[int] = []
    for index, item in enumerate(items):
        compatible = -1
        for prior in range(index - 1, -1, -1):
            if items[prior].candidate.end <= item.candidate.start:
                compatible = prior
                break
        previous.append(compatible)

    best: list[int] = [0]
    scores = [item.priority + len(item.candidate.text) for item in items]
    for index, score in enumerate(scores, start=1):
        include = score + best[previous[index - 1] + 1]
        exclude = best[index - 1]
        if include > exclude:
            best.append(include)
        else:
            best.append(exclude)

    selected: list[_DetectorCandidate] = []
    index = len(items) - 1
    while index >= 0:
        include = scores[index] + best[previous[index] + 1]
        if include > best[index]:
            selected.append(items[index])
            index = previous[index]
        else:
            index -= 1
    return sorted(selected, key=lambda item: (item.candidate.start, item.candidate.end))


def _case_name(citation: object) -> str | None:
    metadata = getattr(citation, "metadata", None)
    plaintiff = getattr(metadata, "plaintiff", None)
    defendant = getattr(metadata, "defendant", None)
    antecedent = getattr(metadata, "antecedent_guess", None)
    if plaintiff and defendant:
        return f"{plaintiff} v. {defendant}"
    return plaintiff or defendant or antecedent
