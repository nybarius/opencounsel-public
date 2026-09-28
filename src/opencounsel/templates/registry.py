from __future__ import annotations

import re
import tomllib
from pathlib import Path

from opencounsel.adapters.word import WordTemplateInspection, inspect_word_template
from opencounsel.templates.ir import StyleBinding, TemplateManifest, TemplateValidation

ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
MAX_MANIFEST_BYTES = 64 * 1024
ROOT_FIELDS_V1 = {
    "schema_version",
    "template_id",
    "version",
    "template_sha256",
    "styles",
    "slots",
}
ROOT_FIELDS_V2 = ROOT_FIELDS_V1 | {"filing_profile_id", "style_pack_id"}
STYLE_FIELDS = {"semantic_role", "word_style_name", "toc_level"}


class TemplateManifestError(ValueError):
    pass


def load_template_manifest(path: Path) -> TemplateManifest:
    if not path.is_file() or path.is_symlink() or path.suffix.lower() != ".toml":
        raise TemplateManifestError("template manifest must be a regular TOML file")
    if path.stat().st_size > MAX_MANIFEST_BYTES:
        raise TemplateManifestError("template manifest exceeds the 64 KiB limit")
    try:
        value = tomllib.loads(path.read_text(encoding="utf-8"))
        schema_version = int(value["schema_version"])
        template_id = str(value["template_id"])
        version = str(value["version"])
        template_sha256 = str(value["template_sha256"])
        raw_styles = value["styles"]
        raw_slots = value.get("slots", [])
    except (KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise TemplateManifestError("template manifest is malformed") from exc

    if schema_version not in {1, 2}:
        raise TemplateManifestError("unsupported template manifest schema version")
    allowed_root_fields = ROOT_FIELDS_V2 if schema_version == 2 else ROOT_FIELDS_V1
    if set(value) - allowed_root_fields:
        raise TemplateManifestError("template manifest contains unknown fields")
    if not ID_RE.fullmatch(template_id):
        raise TemplateManifestError("template_id must be a lowercase stable identifier")
    if not version.strip():
        raise TemplateManifestError("template version must not be empty")
    if not SHA256_RE.fullmatch(template_sha256):
        raise TemplateManifestError("template_sha256 must be a lowercase SHA-256 digest")
    if not isinstance(raw_styles, list) or not raw_styles:
        raise TemplateManifestError("template manifest must bind at least one style")
    if not isinstance(raw_slots, list):
        raise TemplateManifestError("template slots must be a list")
    filing_profile_id: str | None = None
    style_pack_id: str | None = None
    if schema_version == 2:
        try:
            filing_profile_id = str(value["filing_profile_id"])
            style_pack_id = str(value["style_pack_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TemplateManifestError("template manifest is malformed") from exc
        if not ID_RE.fullmatch(filing_profile_id) or not ID_RE.fullmatch(style_pack_id):
            raise TemplateManifestError(
                "filing profile and style-pack IDs must be lowercase stable identifiers"
            )

    styles: list[StyleBinding] = []
    roles: set[str] = set()
    for raw_style in raw_styles:
        if not isinstance(raw_style, dict):
            raise TemplateManifestError("template style binding is malformed")
        if set(raw_style) - STYLE_FIELDS:
            raise TemplateManifestError("template style binding contains unknown fields")
        try:
            role = str(raw_style["semantic_role"])
            style_name = str(raw_style["word_style_name"])
            raw_level = raw_style.get("toc_level")
            toc_level = int(raw_level) if raw_level is not None else None
        except (KeyError, TypeError, ValueError) as exc:
            raise TemplateManifestError("template style binding is malformed") from exc
        if not role or role in roles:
            raise TemplateManifestError("semantic style roles must be nonempty and unique")
        if not style_name:
            raise TemplateManifestError("Word style names must not be empty")
        if toc_level is not None and toc_level not in range(1, 10):
            raise TemplateManifestError("TOC levels must be between 1 and 9")
        roles.add(role)
        styles.append(StyleBinding(role, style_name, toc_level))

    slots = tuple(str(slot) for slot in raw_slots)
    if any(not slot for slot in slots) or len(slots) != len(set(slots)):
        raise TemplateManifestError("template slots must be nonempty and unique")
    return TemplateManifest(
        schema_version,
        template_id,
        version,
        template_sha256,
        tuple(styles),
        slots,
        filing_profile_id,
        style_pack_id,
    )


def validate_word_template(template_path: Path, manifest: TemplateManifest) -> TemplateValidation:
    inspection = inspect_word_template(template_path)
    _validate_inspection(inspection, manifest)
    return TemplateValidation(
        manifest.template_id,
        manifest.version,
        inspection.sha256,
        inspection.section_count,
        tuple(binding.semantic_role for binding in manifest.styles),
    )


def _validate_inspection(inspection: WordTemplateInspection, manifest: TemplateManifest) -> None:
    if inspection.sha256 != manifest.template_sha256:
        raise TemplateManifestError("template hash does not match its manifest")
    missing = sorted(
        binding.word_style_name
        for binding in manifest.styles
        if binding.word_style_name not in inspection.style_names
    )
    if missing:
        raise TemplateManifestError(
            f"template is missing required Word styles: {', '.join(missing)}"
        )
