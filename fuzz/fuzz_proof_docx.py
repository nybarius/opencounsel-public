from __future__ import annotations

import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from opencounsel.briefs.audit import audit_brief
    from opencounsel.briefs.cite_check import citation_review_from_audit
    from opencounsel.briefs.docx import BriefDocxError
    from opencounsel.briefs.front_matter import build_front_matter_source
    from opencounsel.briefs.front_matter_docx import project_front_matter_fields
    from opencounsel.briefs.hyperlink_stage import project_offline_authority_links
    from opencounsel.briefs.proof import plan_proof_corrections
    from opencounsel.briefs.proof_docx import apply_proof_corrections


def test_one_input(data: bytes) -> None:
    with tempfile.TemporaryDirectory(prefix="proof-fuzz-") as temporary:
        source = Path(temporary) / "source.docx"
        proofed = Path(temporary) / "proofed.docx"
        linked = Path(temporary) / "linked.docx"
        output = Path(temporary) / "corrected.docx"
        descriptor = os.open(source, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        with suppress(BriefDocxError):
            plan = plan_proof_corrections(source)
            apply_proof_corrections(source, proofed, plan)
            audit = audit_brief(proofed)
            citation_review_from_audit(audit)
            project_offline_authority_links(proofed, linked, audit)
            front_matter = build_front_matter_source(audit_brief(linked))
            project_front_matter_fields(linked, output, front_matter)


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
