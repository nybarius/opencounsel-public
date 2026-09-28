from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HyperlinkOccurrence:
    text: str
    target: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class BriefParagraph:
    part: str
    paragraph_index: int
    style_id: str | None
    text: str
    hyperlinks: tuple[HyperlinkOccurrence, ...] = ()


@dataclass(frozen=True, slots=True)
class HeadingOccurrence:
    part: str
    paragraph_index: int
    text: str
    style_id: str | None
    level: int
    basis: str


@dataclass(frozen=True, slots=True)
class RecordCitationOccurrence:
    part: str
    paragraph_index: int
    text: str
    start: int
    end: int
    record_pages: tuple[int, ...]
    physical_pdf_pages: tuple[int | None, ...]
    context: str

    @property
    def resolved(self) -> bool:
        return all(page is not None for page in self.physical_pdf_pages)


@dataclass(frozen=True, slots=True)
class AuthorityOccurrence:
    part: str
    paragraph_index: int
    text: str
    normalized_text: str
    case_name: str | None
    start: int
    end: int
    citation_type: str
    category: str
    hyperlink_target: str | None
    groups: tuple[tuple[str, str], ...] = ()
    context: str = ""
    resolved_citation: str | None = None
    resolution_basis: str | None = None
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

    @property
    def is_link_candidate(self) -> bool:
        return self.is_canonical_candidate or self.resolved_citation is not None


@dataclass(frozen=True, slots=True)
class BriefInspection:
    sha256: str
    size_bytes: int
    paragraphs: tuple[BriefParagraph, ...]
    headings: tuple[HeadingOccurrence, ...]


@dataclass(frozen=True, slots=True)
class BriefAudit:
    brief_sha256: str
    brief_size_bytes: int
    headings: tuple[HeadingOccurrence, ...]
    record_citations: tuple[RecordCitationOccurrence, ...]
    authorities: tuple[AuthorityOccurrence, ...]

    @property
    def unresolved_record_citation_count(self) -> int:
        return sum(not citation.resolved for citation in self.record_citations)

    @property
    def unlinked_authority_count(self) -> int:
        return sum(
            authority.is_link_candidate and authority.hyperlink_target is None
            for authority in self.authorities
        )

    @property
    def authority_candidate_count(self) -> int:
        return sum(authority.is_link_candidate for authority in self.authorities)
