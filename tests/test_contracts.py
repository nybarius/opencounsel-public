from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st
from jsonschema import ValidationError
from pydantic import ValidationError as PydanticValidationError

import opencounsel.contracts.schema as schema_module
from opencounsel.contracts.models import (
    CapabilitiesResult,
    CorrectionLedger,
    CorrectionRecord,
    FrontMatterLocation,
    FrontMatterSource,
    ProcessBriefResult,
    RevisionManifest,
    ToaSourceEntry,
    TocSourceEntry,
)
from opencounsel.contracts.schema import load_schema, validate_contract
from opencounsel.objects import ContentAddressedStore


def test_packaged_contracts_are_closed_and_versioned() -> None:
    capabilities = CapabilitiesResult(
        service_version="0.1.0",
        tools=("get_capabilities",),
        transports=("stdio",),
    )
    validate_contract("mcp-capabilities.schema.json", capabilities.model_dump(mode="json"))

    bad = capabilities.model_dump(mode="json") | {"document_text": "must not cross boundary"}
    with pytest.raises(ValidationError):
        validate_contract("mcp-capabilities.schema.json", bad)
    with pytest.raises(PydanticValidationError):
        CapabilitiesResult.model_validate(bad)


def test_schema_loader_has_a_fixed_allowlist() -> None:
    assert load_schema("revision-manifest.schema.json")["type"] == "object"
    with pytest.raises(ValueError, match="unknown contract schema"):
        load_schema("../../private.json")


def test_schema_loader_rejects_oversized_or_non_object_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Resource:
        def __init__(self, data: bytes) -> None:
            self.data = data

        def joinpath(self, name: str) -> Resource:
            return self

        def read_bytes(self) -> bytes:
            return self.data

    oversized = Resource(b"{}")
    monkeypatch.setattr(schema_module, "files", lambda package: oversized)
    monkeypatch.setattr(schema_module, "MAX_SCHEMA_BYTES", 1)
    with pytest.raises(ValueError, match="size limit"):
        load_schema("revision-manifest.schema.json")

    non_object = Resource(b"[]")
    monkeypatch.setattr(schema_module, "files", lambda package: non_object)
    monkeypatch.setattr(schema_module, "MAX_SCHEMA_BYTES", 64 * 1024)
    with pytest.raises(ValueError, match="JSON object"):
        load_schema("revision-manifest.schema.json")


def test_revision_manifest_rejects_malformed_identity() -> None:
    with pytest.raises(PydanticValidationError):
        RevisionManifest(
            revision_id="rev-not-a-hash",
            input_sha256="0" * 64,
            input_size_bytes=1,
            input_object_key=f"sha256/00/{'0' * 62}",
            created_at="2026-01-01T00:00:00+00:00",
        )


def test_process_contracts_are_closed_hash_bound_and_schema_valid() -> None:
    process_id = f"proc-{'1' * 64}"
    revision_id = f"rev-{'2' * 64}"
    ledger = CorrectionLedger(
        process_id=process_id,
        source_revision_id=revision_id,
        input_sha256="2" * 64,
        corrected_sha256="2" * 64,
    )
    result = ProcessBriefResult(
        process_id=process_id,
        source_revision_id=revision_id,
        input_sha256="2" * 64,
        corrected_sha256="2" * 64,
        corrected_size_bytes=123,
        correction_ledger_sha256="3" * 64,
        correction_ledger_size_bytes=456,
        correction_count=0,
        lawyer_review_status="not-required",
        created=True,
    )

    validate_contract("correction-ledger.schema.json", ledger.model_dump(mode="json"))
    validate_contract("process-brief-result.schema.json", result.model_dump(mode="json"))
    with pytest.raises(PydanticValidationError):
        CorrectionLedger.model_validate(
            ledger.model_dump(mode="json") | {"private_prose": "must stay in artifact entries"}
        )

    valid_correction = {
        "correction_id": f"corr-{'4' * 64}",
        "stage": "proof",
        "part": "document",
        "paragraph_index": 1,
        "start_offset": 2,
        "end_offset": 3,
        "original_text": "a",
        "replacement_text": "b",
        "note": "Synthetic correction.",
        "application_status": "applied",
        "basis_sha256": "2" * 64,
    }
    assert CorrectionRecord.model_validate(valid_correction).end_offset == 3
    with pytest.raises(PydanticValidationError, match="offsets are reversed"):
        CorrectionRecord.model_validate(
            valid_correction | {"start_offset": 4, "end_offset": 3}
        )
    citation_finding = valid_correction | {
        "stage": "cite-check",
        "item_type": "authority-citation",
        "replacement_text": "a",
        "application_status": "review-only",
    }
    assert CorrectionRecord.model_validate(citation_finding).item_type == (
        "authority-citation"
    )
    with pytest.raises(PydanticValidationError, match="citation findings"):
        CorrectionRecord.model_validate(citation_finding | {"application_status": "applied"})
    hyperlink = valid_correction | {
        "stage": "hyperlink",
        "item_type": "hyperlink",
        "replacement_text": "a",
    }
    assert CorrectionRecord.model_validate(hyperlink).item_type == "hyperlink"
    with pytest.raises(PydanticValidationError, match="hyperlink findings"):
        CorrectionRecord.model_validate(hyperlink | {"replacement_text": "changed"})
    toc_field = valid_correction | {
        "stage": "toc",
        "item_type": "toc-field",
        "original_text": "[TOC]",
        "replacement_text": "[TOC]",
    }
    assert CorrectionRecord.model_validate(toc_field).item_type == "toc-field"
    with pytest.raises(PydanticValidationError, match="front-matter findings"):
        CorrectionRecord.model_validate(toc_field | {"replacement_text": "changed"})
    with pytest.raises(PydanticValidationError, match="basis"):
        CorrectionLedger(
            process_id=process_id,
            source_revision_id=revision_id,
            transform_id="proof-citation-offline-links",
            input_sha256="2" * 64,
            proofed_sha256="5" * 64,
            corrected_sha256="6" * 64,
            lawyer_review_status="pending",
            corrections=(CorrectionRecord.model_validate(citation_finding),),
        )
    with pytest.raises(PydanticValidationError, match="review state"):
        CorrectionLedger(
            process_id=process_id,
            source_revision_id=revision_id,
            input_sha256="2" * 64,
            corrected_sha256="2" * 64,
            lawyer_review_status="pending",
        )
    with pytest.raises(PydanticValidationError, match="basis"):
        CorrectionLedger(
            process_id=process_id,
            source_revision_id=revision_id,
            transform_id="proof-citation-links-front-matter",
            input_sha256="2" * 64,
            proofed_sha256="5" * 64,
            hyperlinked_sha256="6" * 64,
            corrected_sha256="7" * 64,
            lawyer_review_status="pending",
            corrections=(CorrectionRecord.model_validate(toc_field),),
        )
    with pytest.raises(PydanticValidationError, match="counts are inconsistent"):
        ProcessBriefResult(
            process_id=process_id,
            source_revision_id=revision_id,
            input_sha256="2" * 64,
            corrected_sha256="2" * 64,
            corrected_size_bytes=123,
            correction_ledger_sha256="3" * 64,
            correction_ledger_size_bytes=456,
            correction_count=1,
            lawyer_review_status="pending",
            created=True,
        )


def test_front_matter_contracts_reject_inconsistent_semantics() -> None:
    process_id = f"proc-{'1' * 64}"
    revision_id = f"rev-{'2' * 64}"
    location_data = {
        "part": "document",
        "paragraph_index": 1,
        "start_offset": 0,
        "end_offset": 3,
        "original_text": "abc",
        "citation_type": "SyntheticCitation",
    }
    location = FrontMatterLocation.model_validate(location_data)
    with pytest.raises(PydanticValidationError, match="reversed or empty"):
        FrontMatterLocation.model_validate(
            location_data | {"start_offset": 2, "end_offset": 2}
        )
    with pytest.raises(PydanticValidationError, match="does not match its text"):
        FrontMatterLocation.model_validate(location_data | {"end_offset": 4})

    entry_data = {
        "authority_id": f"fm-toa-{'1' * 64}",
        "category": "cases",
        "word_category": 1,
        "category_heading": "Cases",
        "display_name": "Example v. Synthetic",
        "short_name": "Synthetic",
        "normalized_citation": "Example v. Synthetic, 1 U.S. 2 (2026)",
        "italic_spans": ((0, 20),),
        "locations": (location,),
        "existing_targets": ("https://example.test/a",),
    }
    entry = ToaSourceEntry.model_validate(entry_data)
    with pytest.raises(PydanticValidationError, match="Word category number"):
        ToaSourceEntry.model_validate(
            entry_data | {"category": "statutes", "word_category": 1}
        )
    with pytest.raises(PydanticValidationError, match="italic spans"):
        ToaSourceEntry.model_validate(
            entry_data | {"italic_spans": ((0, 10), (9, 12))}
        )
    with pytest.raises(PydanticValidationError, match="locations must be unique"):
        ToaSourceEntry.model_validate(entry_data | {"locations": (location, location)})
    with pytest.raises(PydanticValidationError, match="sorted and unique"):
        ToaSourceEntry.model_validate(
            entry_data
            | {
                "existing_targets": (
                    "https://example.test/b",
                    "https://example.test/a",
                )
            }
        )

    heading_one = TocSourceEntry(
        entry_id=f"fm-toc-{'2' * 64}",
        level=1,
        heading="FIRST",
        paragraph_index=1,
        basis="paragraph-style",
    )
    heading_zero = TocSourceEntry(
        entry_id=f"fm-toc-{'3' * 64}",
        level=1,
        heading="ZERO",
        paragraph_index=0,
        basis="paragraph-style",
    )
    FrontMatterSource(brief_sha256="4" * 64, toc=(heading_zero, heading_one), toa=(entry,))
    with pytest.raises(PydanticValidationError, match="identities must be unique"):
        FrontMatterSource(brief_sha256="4" * 64, toa=(entry, entry))
    with pytest.raises(PydanticValidationError, match="document order"):
        FrontMatterSource(
            brief_sha256="4" * 64,
            toc=(heading_one, heading_zero),
            toa=(entry,),
        )

    statute = ToaSourceEntry.model_validate(
        entry_data
        | {
            "authority_id": f"fm-toa-{'5' * 64}",
            "category": "statutes",
            "word_category": 2,
            "category_heading": "Statutes",
            "display_name": "Synthetic Code § 1",
            "short_name": "Synthetic Code § 1",
            "normalized_citation": "Synthetic Code § 1",
            "italic_spans": (),
        }
    )
    with pytest.raises(PydanticValidationError, match="category and display order"):
        FrontMatterSource(brief_sha256="4" * 64, toa=(statute, entry))
    with pytest.raises(PydanticValidationError, match="citation review count"):
        ProcessBriefResult(
            process_id=process_id,
            source_revision_id=revision_id,
            input_sha256="2" * 64,
            corrected_sha256="2" * 64,
            corrected_size_bytes=123,
            correction_ledger_sha256="3" * 64,
            correction_ledger_size_bytes=456,
            correction_count=1,
            review_item_count=1,
            authority_citation_count=1,
            citation_review_item_count=2,
            lawyer_review_status="pending",
            created=True,
        )
    with pytest.raises(PydanticValidationError, match="hyperlink counts"):
        ProcessBriefResult(
            process_id=process_id,
            source_revision_id=revision_id,
            input_sha256="2" * 64,
            proofed_sha256="2" * 64,
            corrected_sha256="2" * 64,
            corrected_size_bytes=123,
            correction_ledger_sha256="3" * 64,
            correction_ledger_size_bytes=456,
            correction_count=1,
            applied_correction_count=1,
            hyperlink_candidate_count=1,
            hyperlink_inserted_count=2,
            lawyer_review_status="pending",
            created=True,
        )
    with pytest.raises(PydanticValidationError, match="front-matter field counts"):
        ProcessBriefResult(
            process_id=process_id,
            source_revision_id=revision_id,
            input_sha256="2" * 64,
            corrected_sha256="2" * 64,
            corrected_size_bytes=123,
            correction_ledger_sha256="3" * 64,
            correction_ledger_size_bytes=456,
            correction_count=1,
            applied_correction_count=1,
            front_matter_field_candidate_count=1,
            front_matter_field_applied_count=2,
            lawyer_review_status="pending",
            created=True,
        )


@given(data=st.binary(max_size=4096))
def test_content_store_round_trips_and_deduplicates_arbitrary_bytes(data: bytes) -> None:
    with tempfile.TemporaryDirectory() as temporary:
        store = ContentAddressedStore(Path(temporary) / "objects")
        first = store.put_stream(io.BytesIO(data))
        second = store.put_stream(io.BytesIO(data))

        assert first == second
        with store.open(first.key) as stream:
            assert stream.read() == data
