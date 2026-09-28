"""Pinned symbolic-ai conformance vocabulary, evaluated over local manifest fields.

``supplied`` means that the named local evidence fields are present. It does not
mean a donor gate has admitted the document or that human review has occurred.
The donor is data only; there is no donor runtime, network call or legal decision.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from opencounsel.contracts import ProcessManifest

SCHEMA = "opencounsel.symbolic-ai-conformance/1"
CONTRACT_ROOT = Path(__file__).with_name("symbolic_ai_v1")
DOMAIN_KEY_ID = "sha256:66b4e15e6285169c55e08fde14691e872351197539f835e69bd911a9936ac2cf"
_FIELDS = {
    name: TypeAdapter(field.rebuild_annotation())
    for name, field in ProcessManifest.model_fields.items()
}

BINDINGS = {
    "task_contract_id": ("transform_id", "transform_version"),
    "source_snapshot_ids": ("source_revision_id", "input_sha256"),
    "domain_output_ids": ("corrected_sha256", "correction_ledger_sha256"),
}
PREDICATES = {
    "exact_interface_identity": ("schema_version", "transform_id", "transform_version"),
    "exact_source_snapshot": BINDINGS["source_snapshot_ids"],
    "exact_domain_output_ancestry": (
        "process_id", "source_revision_id", *BINDINGS["domain_output_ids"],
    ),
    "write_set_confinement": ("corrected_object_key", "correction_ledger_object_key"),
    "requested_delta_realization": ("correction_count", "applied_correction_count"),
    "authorized_human_review": ("review_item_count",),
}


def _identity(value: object) -> str:
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def load_contract() -> dict[str, Any]:
    """Read the donor contracts and refuse any mismatch with the domain key."""
    key = json.loads((CONTRACT_ROOT / "domain_key_v1.json").read_text(encoding="utf-8"))
    task = json.loads((CONTRACT_ROOT / "task_contract_v1.json").read_text(encoding="utf-8"))
    policy = json.loads((CONTRACT_ROOT / "verifier_policy_v1.json").read_text(encoding="utf-8"))
    if (
        _identity(key) != DOMAIN_KEY_ID
        or key["domain"] != "symbolic-ai.procedure-precedent"
        or _identity(task) != key["task_contract_id"]
        or _identity(policy) != key["verifier_policy_id"]
    ):
        raise ValueError("symbolic-ai donor contract identity mismatch")
    return {
        "domain": key["domain"],
        "ids": {
            "domain_key_id": _identity(key),
            "task_contract_id": key["task_contract_id"],
            "verifier_policy_id": key["verifier_policy_id"],
        },
        "required_bindings": task["required_bindings"],
        "required_predicates": policy["required_predicates"],
        "negative_laws": policy["negative_laws"],
    }


def conformance(process_manifest: Mapping[str, object]) -> dict[str, Any]:
    """Report exactly which donor obligations have local evidence fields."""
    contract = load_contract()
    _validate_evidence(process_manifest)

    def rows(names: list[str], mapping: Mapping[str, tuple[str, ...]]) -> list[dict[str, Any]]:
        result = []
        for name in names:
            fields = mapping.get(name, ())
            supplied = bool(fields) and all(
                field in process_manifest and process_manifest[field] not in (None, "")
                for field in fields
            )
            result.append({
                "name": name,
                "status": "supplied" if supplied else "unsupplied",
                "fields": list(fields) if supplied else [],
            })
        return result

    bindings = rows(contract["required_bindings"], BINDINGS)
    predicates = rows(contract["required_predicates"], PREDICATES)
    return {
        "schema": SCHEMA,
        "relationship": "CONFORMS_TO",
        "domain": contract["domain"],
        "ids": contract["ids"],
        "process_id": process_manifest.get("process_id"),
        "manifest_id": _identity(dict(process_manifest)),
        "scope": "Local evidence-field coverage; no donor admission or human approval is asserted.",
        "bindings": bindings,
        "predicates": predicates,
        "counts": {
            "bindings_supplied": sum(row["status"] == "supplied" for row in bindings),
            "bindings": len(bindings),
            "predicates_supplied": sum(row["status"] == "supplied" for row in predicates),
            "predicates": len(predicates),
        },
        "negative_laws": contract["negative_laws"],
    }


def _validate_evidence(manifest: Mapping[str, object]) -> None:
    """Reuse the core schema without inventing defaults for missing evidence."""
    for name, value in manifest.items():
        if name not in _FIELDS:
            raise ValueError("unknown process manifest field")
        _FIELDS[name].validate_python(value, strict=True)
    for prefix in ("corrected", "correction_ledger", "front_matter_source"):
        key = manifest.get(prefix + "_object_key")
        digest = manifest.get(prefix + "_sha256")
        expected = f"sha256/{str(digest)[:2]}/{str(digest)[2:]}"
        if key is not None and digest is not None and key != expected:
            raise ValueError("object key does not bind its output digest")
    total, applied, review = (manifest.get(name) for name in (
        "correction_count", "applied_correction_count", "review_item_count",
    ))
    if (
        isinstance(total, int) and isinstance(applied, int) and isinstance(review, int)
        and total != applied + review
    ):
        raise ValueError("process correction counts are inconsistent")
    required = {name for name, field in ProcessManifest.model_fields.items() if field.is_required()}
    if required <= manifest.keys():
        ProcessManifest.model_validate(dict(manifest), strict=True)
