"""Deterministic brief inspection and audit primitives."""

from opencounsel.briefs.audit import audit_brief
from opencounsel.briefs.cite_check import plan_citation_review
from opencounsel.briefs.docx import BriefDocxError, inspect_brief_docx
from opencounsel.briefs.front_matter import build_front_matter_source
from opencounsel.briefs.front_matter_docx import project_front_matter_fields
from opencounsel.briefs.hyperlink_stage import project_offline_authority_links
from opencounsel.briefs.proof import plan_proof_corrections

__all__ = [
    "BriefDocxError",
    "audit_brief",
    "build_front_matter_source",
    "inspect_brief_docx",
    "plan_citation_review",
    "plan_proof_corrections",
    "project_front_matter_fields",
    "project_offline_authority_links",
]
