"""RED: symbolic-ai as a conformance donor (CONFORMS_TO, never a runtime import).

symbolic-ai's procedural-authority-compiler interface (`domain_key_v1`, `task_contract_v1`,
`verifier_policy_v1`, pinned by the sha256 ids the domain key declares) names the bindings a
candidate must carry and the predicates a verifier must read, and its negative laws. The adapter
reports, for one OpenCounsel process manifest, which of those bindings and predicates the manifest
supplies and by which field, and which it does not; it claims nothing it cannot bind, and it quotes
the negative laws verbatim. It never imports symbolic-ai.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from opencounsel.adapters import symbolic_ai as donor

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "src" / "opencounsel" / "adapters" / "symbolic_ai_v1"

MANIFEST = {
    "schema_version": 1,
    "process_id": "proc-" + "a" * 64,
    "status": "completed",
    "source_revision_id": "rev-" + "b" * 64,
    "transform_id": "proof-citation-links-front-matter",
    "transform_version": "1",
    "input_sha256": "c" * 64,
    "corrected_sha256": "d" * 64,
    "corrected_size_bytes": 10,
    "corrected_object_key": "sha256/dd/" + "d" * 62,
    "correction_ledger_sha256": "e" * 64,
    "correction_ledger_size_bytes": 5,
    "correction_ledger_object_key": "sha256/ee/" + "e" * 62,
    "correction_count": 3,
    "applied_correction_count": 2,
    "review_item_count": 1,
}


def test_the_donor_contract_is_pinned_by_its_own_ids() -> None:
    contract = donor.load_contract()
    key = json.loads((FIXTURES / "domain_key_v1.json").read_text())
    assert contract["domain"] == "symbolic-ai.procedure-precedent"
    for name, want in (
        ("task_contract_v1.json", key["task_contract_id"]),
        ("verifier_policy_v1.json", key["verifier_policy_id"]),
    ):
        # the donor's id recipe: sha256 of the sorted, compact JSON (symbolic_ai.institution.packet)
        canonical = json.dumps(
            json.loads((FIXTURES / name).read_text()), sort_keys=True, separators=(",", ":")
        )
        got = "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()
        assert got == want
    assert contract["ids"]["task_contract_id"] == key["task_contract_id"]
    assert "verification does not establish legal truth" in contract["negative_laws"]


def test_conformance_binds_what_the_manifest_supplies_and_claims_nothing_else() -> None:
    report = donor.conformance(MANIFEST)
    assert report["schema"] == donor.SCHEMA
    bound = {row["name"]: row for row in report["bindings"]}
    assert bound["source_snapshot_ids"]["status"] == "supplied"
    assert set(bound["source_snapshot_ids"]["fields"]) == {"source_revision_id", "input_sha256"}
    assert bound["domain_output_ids"]["status"] == "supplied"
    assert "corrected_sha256" in bound["domain_output_ids"]["fields"]
    # OpenCounsel keeps no predecessor chain here.
    assert bound["predecessor_ids"]["status"] == "unsupplied"
    preds = {row["name"]: row for row in report["predicates"]}
    assert preds["exact_source_snapshot"]["status"] == "supplied"
    assert preds["write_set_confinement"]["status"] == "supplied"
    assert preds["authorized_human_review"]["status"] == "supplied"
    assert preds["authorized_human_review"]["fields"] == ["review_item_count"]
    assert preds["coverage_closure"]["status"] == "unsupplied"
    assert preds["exact_interface_identity"]["status"] == "supplied"
    assert report["negative_laws"] == donor.load_contract()["negative_laws"]
    assert report["counts"] == {
        "bindings_supplied": 3, "bindings": 7, "predicates_supplied": 6, "predicates": 11,
    }
    assert "legal truth" not in json.dumps(report["bindings"])  # no claim of truth anywhere


def test_the_adapter_never_imports_symbolic_ai() -> None:
    source = (ROOT / "src" / "opencounsel" / "adapters" / "symbolic_ai.py").read_text()
    assert "import symbolic_ai" not in source and "from symbolic_ai" not in source
