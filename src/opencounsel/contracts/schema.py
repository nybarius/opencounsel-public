from __future__ import annotations

import json
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator

SCHEMA_NAMES = frozenset(
    {
        "brief-inspection.schema.json",
        "correction-ledger.schema.json",
        "front-matter-source.schema.json",
        "mcp-capabilities.schema.json",
        "process-brief-result.schema.json",
        "process-manifest.schema.json",
        "publication-manifest.schema.json",
        "revision-manifest.schema.json",
    }
)
MAX_SCHEMA_BYTES = 64 * 1024


def load_schema(name: str) -> dict[str, Any]:
    """Load one packaged schema from a fixed allowlist."""
    if name not in SCHEMA_NAMES:
        raise ValueError(f"unknown contract schema: {name}")
    data = files("opencounsel.contracts.schemas").joinpath(name).read_bytes()
    if len(data) > MAX_SCHEMA_BYTES:
        raise ValueError(f"contract schema exceeds size limit: {name}")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise ValueError(f"contract schema must be a JSON object: {name}")
    Draft202012Validator.check_schema(value)
    return value


def validate_contract(name: str, payload: dict[str, Any]) -> None:
    """Raise jsonschema.ValidationError when a payload violates its contract."""
    Draft202012Validator(load_schema(name)).validate(payload)
