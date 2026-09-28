from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_compose_is_a_named_loopback_only_local_application() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

    assert compose.startswith("name: opencounsel\n")
    assert '"127.0.0.1:8765:8765"' in compose
    assert "opencounsel-data:/home/opencounsel/data" in compose
    assert "read_only: true" in compose
    assert "cap_drop:\n      - ALL" in compose
    assert "no-new-privileges:true" in compose
    assert "init: true" in compose


def test_container_has_an_executable_readiness_contract() -> None:
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert "HEALTHCHECK" in dockerfile
    assert "http://127.0.0.1:8765/healthz" in dockerfile
    assert "healthcheck:" in compose
    assert "127.0.0.1:8765/healthz" in compose


def test_readme_contains_the_complete_operator_path() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")

    assert "docker compose up --build" in readme
    assert "http://127.0.0.1:8765" in readme
    assert "Run the OpenAI filing demo" in readme
    assert "docker compose ps" in readme
    assert "healthy" in readme
    assert "docker compose down" in readme
    assert "docker compose down --volumes" in readme
    assert "opencounsel-data" in readme
    expected_requirement = "No host Python, PostgreSQL, or LibreOffice installation is required."
    assert expected_requirement in readme


def test_ci_executes_the_clean_state_two_pass_compose_rehearsal() -> None:
    script_path = ROOT / "scripts" / "rehearse_compose_demo.sh"
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    assert script_path.is_file()
    script = script_path.read_text(encoding="utf-8")
    assert script.startswith("#!/bin/sh\n")
    assert "compose down --volumes" in script
    assert "compose build" in script
    assert "compose up --detach" in script
    assert 'client.post("/api/demo", expected=(202,))' in script
    assert 'artifact(client, job_id, "document")' in script
    assert 'artifact(client, job_id, "pdf")' in script
    assert 'f"/api/jobs/{job_id}/sources"' in script
    assert 'f"/api/jobs/{job_id}/links"' in script
    assert 'artifact(client, job_id, "linked-document")' in script
    assert 'artifact(client, job_id, "linked-pdf")' in script
    assert 'method="DELETE"' in script
    assert "compose-rehearsal-report.json" in script
    assert "scripts/rehearse_compose_demo.sh" in workflow


def test_compose_rehearsal_uploads_only_requested_authority_sources() -> None:
    script = (ROOT / "scripts" / "rehearse_compose_demo.sh").read_text(
        encoding="utf-8"
    )

    assert 'source.get("status") == "source-copy-required"' in script
    assert "did not declare exactly four authority upload slots" in script


def test_compose_rehearsal_maps_prepared_sources_by_canonical_citation() -> None:
    script = (ROOT / "scripts" / "rehearse_compose_demo.sh").read_text(
        encoding="utf-8"
    ).casefold()

    for citation in ("101 u.s. 99", "464 u.s. 417", "556 u.s. 662", "804 f.3d 202"):
        assert citation in script
