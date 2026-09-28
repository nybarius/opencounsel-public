"""C10's donor checks must reach the actual review package without granting approval."""

from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from types import SimpleNamespace

import pytest
from test_symbolic_ai_conformance import MANIFEST

from opencounsel.adapters import symbolic_ai as donor
from opencounsel.demo import build_synthetic_demo
from opencounsel.web import jobs


@pytest.mark.parametrize(
    "change",
    [
        {"corrected_sha256": "bad"},
        {"corrected_object_key": "../../outside"},
        {"corrected_object_key": "sha256/ff/" + "f" * 62},
        {"review_item_count": -1},
        {"review_item_count": True},
        {"review_item_count": 7},
        {"schema_version": 2},
        {"transform_id": "not-an-interface"},
        {"surprise_approval": True},
    ],
)
def test_invalid_evidence_is_refused(change: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        donor.conformance(dict(MANIFEST, **change))


def test_empty_evidence_does_not_claim_any_supplied_obligation() -> None:
    report = donor.conformance({})
    assert report["counts"]["bindings_supplied"] == 0
    assert report["counts"]["predicates_supplied"] == 0
    assert all(not row["fields"] for row in report["bindings"] + report["predicates"])


def test_coherent_donor_substitution_cannot_change_the_pinned_contract(
    tmp_path, monkeypatch
) -> None:
    shutil.copytree(donor.CONTRACT_ROOT, tmp_path / "donor")
    root = tmp_path / "donor"
    policy_path = root / "verifier_policy_v1.json"
    policy = json.loads(policy_path.read_text())
    policy["required_predicates"] = []
    policy_path.write_text(json.dumps(policy))
    key_path = root / "domain_key_v1.json"
    key = json.loads(key_path.read_text())
    key["verifier_policy_id"] = (
        "sha256:"
        + hashlib.sha256(
            json.dumps(policy, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
    )
    key_path.write_text(json.dumps(key))
    monkeypatch.setattr(donor, "CONTRACT_ROOT", root)
    with pytest.raises(ValueError, match="identity"):
        donor.load_contract()


def test_real_process_checks_are_downloadable_and_survive_final_packaging(tmp_path, monkeypatch):
    # Keep the real document/core path; publication rendering has its own engine tests.
    def publish(store, process_id, *, executable):
        delivery = store.deliveries / process_id
        shutil.copyfile(delivery / "corrected.docx", delivery / "published.docx")
        (delivery / "published.pdf").write_bytes(b"%PDF synthetic publication")
        (delivery / "publication.json").write_text("{}")
        return SimpleNamespace(
            page_count=1,
            engine="synthetic",
            engine_version="1",
            output_docx_sha256=hashlib.sha256(
                (delivery / "published.docx").read_bytes()
            ).hexdigest(),
            output_pdf_sha256=hashlib.sha256((delivery / "published.pdf").read_bytes()).hexdigest(),
        )

    def render(source, destination, *, executable):
        destination.write_bytes(b"%PDF synthetic original")

    monkeypatch.setattr(jobs, "publish_foss", publish)
    monkeypatch.setattr(jobs, "render_docx_reference_pdf", render)
    manager = jobs.JobManager(tmp_path / "jobs")
    context = manager.reserve(
        profile_id="ny-ad-appellant-brief",
        brief_name="synthetic-appellant-brief.docx",
        roa_name="synthetic-record.zip",
        demo=True,
    ).context
    try:
        build_synthetic_demo(context.inbox_dir)
        result = manager._execute(context)
        assert "error" not in result, result
        artifact = manager.artifact(context.job_id, "conformance")
        report = json.loads(artifact.path.read_text())
        process_id = result["audit"]["process_id"]
        manifest = json.loads(manager.artifact(context.job_id, "process").path.read_text())
        assert report == donor.conformance(manifest)
        assert report["process_id"] == process_id
        assert report["counts"] == {
            "bindings": 7,
            "bindings_supplied": 3,
            "predicates": 11,
            "predicates_supplied": 6,
        }
        assert "no donor admission or human approval" in report["scope"]
        with zipfile.ZipFile(manager.artifact(context.job_id, "package").path) as package:
            assert package.read("symbolic-ai-conformance.json") == artifact.path.read_bytes()
            assert json.loads(package.read("process.json")) == manifest
        authority = tmp_path / "authority.zip"
        authority.write_bytes(b"synthetic authority package")
        verification = tmp_path / "verification.json"
        verification.write_text("{}")
        final = tmp_path / "final.zip"
        jobs._write_final_review_package(final, context.job_dir / "export", authority, verification)
        with zipfile.ZipFile(final) as package:
            assert (
                package.read("first-pass/symbolic-ai-conformance.json")
                == artifact.path.read_bytes()
            )
    finally:
        manager.close()
