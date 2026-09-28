"""Rule-aware blank Word templates, separate from matter content."""

from opencounsel.templates.audit import audit_word_styles, write_style_audit
from opencounsel.templates.build import build_blank_word_template
from opencounsel.templates.profiles import (
    FilingProfileError,
    get_bundled_filing_profile,
    list_bundled_filing_profiles,
)
from opencounsel.templates.registry import (
    TemplateManifestError,
    load_template_manifest,
    validate_word_template,
)

__all__ = [
    "FilingProfileError",
    "TemplateManifestError",
    "audit_word_styles",
    "build_blank_word_template",
    "get_bundled_filing_profile",
    "list_bundled_filing_profiles",
    "load_template_manifest",
    "validate_word_template",
    "write_style_audit",
]
