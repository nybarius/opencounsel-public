from __future__ import annotations

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContractModel(BaseModel):
    """Closed, immutable base for data that crosses a process boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RevisionManifest(ContractModel):
    schema_version: Literal[1] = 1
    revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    status: Literal["prepared"] = "prepared"
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_size_bytes: int = Field(ge=0)
    input_object_key: str = Field(pattern=r"^sha256/[0-9a-f]{2}/[0-9a-f]{62}$")
    created_at: str


class CapabilitiesResult(ContractModel):
    schema_version: Literal[1] = 1
    service: Literal["opencounsel"] = "opencounsel"
    service_version: str
    tools: tuple[str, ...]
    transports: tuple[Literal["stdio", "streamable-http"], ...]
    network_policy: Literal["disabled"] = "disabled"
    model_policy: Literal["disabled"] = "disabled"


class CreateRevisionResult(ContractModel):
    schema_version: Literal[1] = 1
    revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    status: Literal["prepared"] = "prepared"
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_size_bytes: int = Field(ge=0)
    created: bool


class BriefInspectionResult(ContractModel):
    schema_version: Literal[1] = 1
    revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    brief_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(ge=0)
    paragraph_count: int = Field(ge=0)
    heading_count: int = Field(ge=0)
    part_counts: dict[str, int]
    external_link_count: int = Field(ge=0)


class FrontMatterLocation(ContractModel):
    """One exact, page-free Word occurrence used by a front-matter projection."""

    part: str = Field(min_length=1, max_length=128)
    paragraph_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    original_text: str = Field(min_length=1, max_length=16_384)
    citation_type: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def span_matches_text(self) -> Self:
        if self.end_offset <= self.start_offset:
            raise ValueError("front-matter location offsets are reversed or empty")
        if self.end_offset - self.start_offset != len(self.original_text):
            raise ValueError("front-matter location span does not match its text")
        return self


class TocSourceEntry(ContractModel):
    """Semantic heading identity without a rendered page number."""

    entry_id: str = Field(pattern=r"^fm-toc-[0-9a-f]{64}$")
    level: int = Field(ge=1, le=9)
    heading: str = Field(min_length=1, max_length=16_384)
    number_label: str | None = Field(default=None, max_length=32)
    part: Literal["document"] = "document"
    paragraph_index: int = Field(ge=0)
    style_id: str | None = Field(default=None, max_length=256)
    basis: str = Field(min_length=1, max_length=128)


FrontMatterCategory = Literal[
    "cases",
    "statutes",
    "other-authorities",
    "rules",
    "treatises",
    "regulations",
    "constitutional-provisions",
]


class ToaSourceEntry(ContractModel):
    """Canonical authority identity and exact occurrences without pagination."""

    authority_id: str = Field(pattern=r"^fm-toa-[0-9a-f]{64}$")
    category: FrontMatterCategory
    word_category: int = Field(ge=1, le=7)
    category_heading: str = Field(min_length=1, max_length=256)
    display_name: str = Field(min_length=1, max_length=16_384)
    short_name: str = Field(min_length=1, max_length=4_096)
    normalized_citation: str = Field(min_length=1, max_length=4_096)
    italic_spans: tuple[tuple[int, int], ...] = ()
    locations: tuple[FrontMatterLocation, ...] = Field(min_length=1)
    existing_targets: tuple[str, ...] = ()

    @model_validator(mode="after")
    def category_and_spans_are_valid(self) -> Self:
        expected = {
            "cases": 1,
            "statutes": 2,
            "other-authorities": 3,
            "rules": 4,
            "treatises": 5,
            "regulations": 6,
            "constitutional-provisions": 7,
        }[self.category]
        if self.word_category != expected:
            raise ValueError("TOA category does not match its Word category number")
        previous_end = 0
        for start, end in self.italic_spans:
            if start < previous_end or end <= start or end > len(self.display_name):
                raise ValueError("TOA italic spans are invalid")
            previous_end = end
        identities = {
            (item.part, item.paragraph_index, item.start_offset, item.end_offset)
            for item in self.locations
        }
        if len(identities) != len(self.locations):
            raise ValueError("TOA locations must be unique")
        if tuple(sorted(set(self.existing_targets))) != self.existing_targets:
            raise ValueError("TOA existing targets must be sorted and unique")
        return self


class FrontMatterSource(ContractModel):
    """Private semantic TOC/TOA input, deliberately excluding rendered pages."""

    schema_version: Literal[1] = 1
    brief_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    toc: tuple[TocSourceEntry, ...] = ()
    toa: tuple[ToaSourceEntry, ...] = ()
    excluded_authority_occurrence_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def identities_and_order_are_stable(self) -> Self:
        toc_ids = {item.entry_id for item in self.toc}
        toa_ids = {item.authority_id for item in self.toa}
        if len(toc_ids) != len(self.toc) or len(toa_ids) != len(self.toa):
            raise ValueError("front-matter identities must be unique")
        toc_order = tuple((item.part, item.paragraph_index, item.level) for item in self.toc)
        if tuple(sorted(toc_order)) != toc_order:
            raise ValueError("TOC source entries must follow document order")
        toa_order = tuple(
            (item.word_category, item.display_name.casefold(), item.normalized_citation.casefold())
            for item in self.toa
        )
        if tuple(sorted(toa_order)) != toa_order:
            raise ValueError("TOA source entries must follow category and display order")
        return self


class CorrectionRecord(ContractModel):
    """One reviewable change applied to a delivery DOCX."""

    correction_id: str = Field(pattern=r"^corr-[0-9a-f]{64}$")
    stage: Literal["proof", "cite-check", "hyperlink", "toc", "toa", "template"]
    item_type: Literal[
        "correction",
        "record-citation",
        "authority-citation",
        "hyperlink",
        "toc-heading",
        "toa-authority",
        "toc-field",
        "toa-field",
    ] = "correction"
    basis_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    part: str = Field(min_length=1, max_length=128)
    paragraph_index: int = Field(ge=0)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)
    original_text: str = Field(max_length=16_384)
    replacement_text: str = Field(max_length=16_384)
    note: str = Field(min_length=1, max_length=16_384)
    application_status: Literal["applied", "review-only"] = "applied"
    review_status: Literal["pending", "accepted", "rejected"] = "pending"

    @model_validator(mode="after")
    def offsets_are_ordered(self) -> Self:
        if self.end_offset < self.start_offset:
            raise ValueError("correction offsets are reversed")
        citation_item = self.item_type in {"record-citation", "authority-citation"}
        if citation_item and (
            self.stage != "cite-check"
            or self.application_status != "review-only"
            or self.original_text != self.replacement_text
        ):
            raise ValueError("citation findings must be unchanged cite-check review items")
        if self.stage == "cite-check" and not citation_item:
            raise ValueError("citation findings must declare their citation item type")
        if self.item_type == "hyperlink" and (
            self.stage != "hyperlink" or self.original_text != self.replacement_text
        ):
            raise ValueError("hyperlink findings must preserve text and use the hyperlink stage")
        if self.stage == "hyperlink" and self.item_type != "hyperlink":
            raise ValueError("hyperlink findings must declare their hyperlink item type")
        front_matter_items = {"toc-heading", "toa-authority", "toc-field", "toa-field"}
        if self.item_type in front_matter_items:
            expected_stage = "toc" if self.item_type.startswith("toc-") else "toa"
            if self.stage != expected_stage or self.original_text != self.replacement_text:
                raise ValueError(
                    "front-matter findings must preserve text and match their stage"
                )
        if self.stage in {"toc", "toa"} and self.item_type not in front_matter_items:
            raise ValueError("front-matter findings must declare their field item type")
        return self


class CorrectionLedger(ContractModel):
    """Private, machine-readable notes for Word Compare and lawyer review."""

    schema_version: Literal[1] = 1
    process_id: str = Field(pattern=r"^proc-[0-9a-f]{64}$")
    source_revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    transform_id: Literal[
        "baseline-copy",
        "proof-punctuation",
        "proof-punctuation-citation-audit",
        "proof-citation-offline-links",
        "proof-citation-links-front-matter",
    ] = "baseline-copy"
    transform_version: Literal["1"] = "1"
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authority_resolution_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    proofed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    hyperlinked_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    corrected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    lawyer_review_status: Literal["not-required", "pending"] = "not-required"
    corrections: tuple[CorrectionRecord, ...] = ()

    @model_validator(mode="after")
    def review_state_matches_corrections(self) -> Self:
        expected = "pending" if self.corrections else "not-required"
        if self.lawyer_review_status != expected:
            raise ValueError("ledger review state does not match its corrections")
        if self.transform_id == "proof-citation-offline-links":
            if self.proofed_sha256 is None:
                raise ValueError("staged ledger must identify its proofed document hash")
            for item in self.corrections:
                expected_basis = (
                    self.input_sha256 if item.stage == "proof" else self.proofed_sha256
                )
                if item.basis_sha256 != expected_basis:
                    raise ValueError("ledger item basis does not match its stage document")
        if self.transform_id == "proof-citation-links-front-matter":
            if self.proofed_sha256 is None or self.hyperlinked_sha256 is None:
                raise ValueError("front-matter ledger must identify each stage document hash")
            for item in self.corrections:
                if item.stage == "proof":
                    expected_basis = self.input_sha256
                elif item.stage in {"cite-check", "hyperlink"}:
                    expected_basis = self.proofed_sha256
                else:
                    expected_basis = self.hyperlinked_sha256
                if item.basis_sha256 != expected_basis:
                    raise ValueError("ledger item basis does not match its stage document")
        return self


class ProcessManifest(ContractModel):
    """Immutable record binding one transform to its private artifacts."""

    schema_version: Literal[1] = 1
    process_id: str = Field(pattern=r"^proc-[0-9a-f]{64}$")
    status: Literal["completed"] = "completed"
    source_revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    transform_id: Literal[
        "baseline-copy",
        "proof-punctuation",
        "proof-punctuation-citation-audit",
        "proof-citation-offline-links",
        "proof-citation-links-front-matter",
    ] = "baseline-copy"
    transform_version: Literal["1"] = "1"
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authority_resolution_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    proofed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    hyperlinked_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    corrected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corrected_size_bytes: int = Field(ge=0)
    corrected_object_key: str = Field(pattern=r"^sha256/[0-9a-f]{2}/[0-9a-f]{62}$")
    correction_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    correction_ledger_size_bytes: int = Field(ge=0)
    correction_ledger_object_key: str = Field(
        pattern=r"^sha256/[0-9a-f]{2}/[0-9a-f]{62}$"
    )
    front_matter_source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    front_matter_source_size_bytes: int = Field(default=0, ge=0)
    front_matter_source_object_key: str | None = Field(
        default=None, pattern=r"^sha256/[0-9a-f]{2}/[0-9a-f]{62}$"
    )
    correction_count: int = Field(ge=0)
    applied_correction_count: int = Field(default=0, ge=0)
    review_item_count: int = Field(default=0, ge=0)
    record_citation_count: int = Field(default=0, ge=0)
    resolved_record_citation_count: int = Field(default=0, ge=0)
    unresolved_record_citation_count: int = Field(default=0, ge=0)
    authority_citation_count: int = Field(default=0, ge=0)
    citation_review_item_count: int = Field(default=0, ge=0)
    hyperlink_candidate_count: int = Field(default=0, ge=0)
    hyperlink_inserted_count: int = Field(default=0, ge=0)
    hyperlink_review_item_count: int = Field(default=0, ge=0)
    toc_entry_count: int = Field(default=0, ge=0)
    toa_authority_count: int = Field(default=0, ge=0)
    toa_occurrence_count: int = Field(default=0, ge=0)
    front_matter_field_candidate_count: int = Field(default=0, ge=0)
    front_matter_field_applied_count: int = Field(default=0, ge=0)
    front_matter_field_review_item_count: int = Field(default=0, ge=0)
    toc_field_inserted_count: int = Field(default=0, ge=0)
    toa_field_inserted_count: int = Field(default=0, ge=0)
    lawyer_review_status: Literal["not-required", "pending"]
    created_at: str

    @model_validator(mode="after")
    def counts_are_consistent(self) -> Self:
        if self.correction_count != (
            self.applied_correction_count + self.review_item_count
        ):
            raise ValueError("process correction counts are inconsistent")
        if self.citation_review_item_count > self.review_item_count or (
            self.citation_review_item_count
            > self.record_citation_count + self.authority_citation_count
        ):
            raise ValueError("process citation review count is inconsistent")
        resolution_counts = (
            self.resolved_record_citation_count
            + self.unresolved_record_citation_count
        )
        if resolution_counts and self.record_citation_count != resolution_counts:
            raise ValueError("process record-citation resolution counts are inconsistent")
        if self.hyperlink_candidate_count != (
            self.hyperlink_inserted_count + self.hyperlink_review_item_count
        ) or self.hyperlink_inserted_count > self.applied_correction_count or (
            self.hyperlink_review_item_count > self.review_item_count
        ):
            raise ValueError("process hyperlink counts are inconsistent")
        if self.front_matter_field_candidate_count != (
            self.front_matter_field_applied_count
            + self.front_matter_field_review_item_count
        ) or self.front_matter_field_applied_count > self.applied_correction_count or (
            self.front_matter_field_review_item_count > self.review_item_count
        ):
            raise ValueError("process front-matter field counts are inconsistent")
        if self.toa_occurrence_count < self.toa_authority_count:
            raise ValueError("process TOA semantic counts are inconsistent")
        if self.toc_field_inserted_count > 1 or self.toa_field_inserted_count > 1:
            raise ValueError("process front-matter slot counts are inconsistent")
        if (
            self.transform_id == "proof-citation-offline-links"
            and self.proofed_sha256 is None
        ):
            raise ValueError("staged process must identify its proofed document hash")
        if self.transform_id == "proof-citation-links-front-matter" and (
            self.proofed_sha256 is None
            or self.hyperlinked_sha256 is None
            or self.front_matter_source_sha256 is None
            or self.front_matter_source_size_bytes == 0
            or self.front_matter_source_object_key is None
        ):
            raise ValueError("front-matter process must identify every staged artifact")
        expected = "pending" if self.correction_count else "not-required"
        if self.lawyer_review_status != expected:
            raise ValueError("process review state does not match its corrections")
        return self


class ProcessBriefResult(ContractModel):
    """Metadata-only process result safe for CLI and MCP orchestration."""

    schema_version: Literal[1] = 1
    process_id: str = Field(pattern=r"^proc-[0-9a-f]{64}$")
    status: Literal["completed"] = "completed"
    source_revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    input_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    record_source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    authority_resolution_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    proofed_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    hyperlinked_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    corrected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corrected_size_bytes: int = Field(ge=0)
    correction_ledger_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    correction_ledger_size_bytes: int = Field(ge=0)
    front_matter_source_sha256: str | None = Field(
        default=None, pattern=r"^[0-9a-f]{64}$"
    )
    front_matter_source_size_bytes: int = Field(default=0, ge=0)
    correction_count: int = Field(ge=0)
    applied_correction_count: int = Field(default=0, ge=0)
    review_item_count: int = Field(default=0, ge=0)
    record_citation_count: int = Field(default=0, ge=0)
    resolved_record_citation_count: int = Field(default=0, ge=0)
    unresolved_record_citation_count: int = Field(default=0, ge=0)
    authority_citation_count: int = Field(default=0, ge=0)
    citation_review_item_count: int = Field(default=0, ge=0)
    hyperlink_candidate_count: int = Field(default=0, ge=0)
    hyperlink_inserted_count: int = Field(default=0, ge=0)
    hyperlink_review_item_count: int = Field(default=0, ge=0)
    toc_entry_count: int = Field(default=0, ge=0)
    toa_authority_count: int = Field(default=0, ge=0)
    toa_occurrence_count: int = Field(default=0, ge=0)
    front_matter_field_candidate_count: int = Field(default=0, ge=0)
    front_matter_field_applied_count: int = Field(default=0, ge=0)
    front_matter_field_review_item_count: int = Field(default=0, ge=0)
    toc_field_inserted_count: int = Field(default=0, ge=0)
    toa_field_inserted_count: int = Field(default=0, ge=0)
    lawyer_review_status: Literal["not-required", "pending"]
    created: bool

    @model_validator(mode="after")
    def counts_are_consistent(self) -> Self:
        if self.correction_count != (
            self.applied_correction_count + self.review_item_count
        ):
            raise ValueError("process correction counts are inconsistent")
        if self.citation_review_item_count > self.review_item_count or (
            self.citation_review_item_count
            > self.record_citation_count + self.authority_citation_count
        ):
            raise ValueError("process citation review count is inconsistent")
        resolution_counts = (
            self.resolved_record_citation_count
            + self.unresolved_record_citation_count
        )
        if resolution_counts and self.record_citation_count != resolution_counts:
            raise ValueError("process record-citation resolution counts are inconsistent")
        if self.hyperlink_candidate_count != (
            self.hyperlink_inserted_count + self.hyperlink_review_item_count
        ) or self.hyperlink_inserted_count > self.applied_correction_count or (
            self.hyperlink_review_item_count > self.review_item_count
        ):
            raise ValueError("process hyperlink counts are inconsistent")
        if self.front_matter_field_candidate_count != (
            self.front_matter_field_applied_count
            + self.front_matter_field_review_item_count
        ) or self.front_matter_field_applied_count > self.applied_correction_count or (
            self.front_matter_field_review_item_count > self.review_item_count
        ):
            raise ValueError("process front-matter field counts are inconsistent")
        if self.toa_occurrence_count < self.toa_authority_count:
            raise ValueError("process TOA semantic counts are inconsistent")
        if self.toc_field_inserted_count > 1 or self.toa_field_inserted_count > 1:
            raise ValueError("process front-matter slot counts are inconsistent")
        expected = "pending" if self.correction_count else "not-required"
        if self.lawyer_review_status != expected:
            raise ValueError("process review state does not match its corrections")
        return self


class CleanBriefResult(ContractModel):
    """One complete prepared-brief result without private paths or document prose."""

    schema_version: Literal[1] = 1
    status: Literal["completed"] = "completed"
    profile_id: str = Field(min_length=1, max_length=128)
    source_revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    normalized_revision_id: str = Field(pattern=r"^rev-[0-9a-f]{64}$")
    formatting_applied_count: int = Field(ge=0)
    authority_link_inserted_count: int = Field(ge=0)
    authority_link_review_count: int = Field(ge=0)
    process: ProcessBriefResult
