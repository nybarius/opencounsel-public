from __future__ import annotations

import threading
from pathlib import Path

from starlette.testclient import TestClient

from opencounsel.web.app import create_app
from opencounsel.web.jobs import JobContext, JobManager, ProgressUpdate


def test_public_demo_reserves_the_explicit_no_record_path(tmp_path: Path) -> None:
    started = threading.Event()
    captured: dict[str, JobContext] = {}

    def processor(
        context: JobContext,
        _progress: ProgressUpdate,
    ) -> dict[str, object]:
        captured["context"] = context
        started.set()
        return {"summary": {}, "sources": [], "audit": {}, "artifacts": {}}

    manager = JobManager(tmp_path / "jobs", processor=processor)
    with TestClient(create_app(manager=manager)) as client:
        response = client.post("/api/demo")
        assert response.status_code == 202
        assert started.wait(timeout=1)
        snapshot = client.get(f"/api/jobs/{response.json()['job_id']}").json()

    assert snapshot["record_mode"] == "no-record"
    assert snapshot["roa_name"] is None
    assert snapshot["profile"]["profile_id"] == "fed-sdny-edny-motion-memorandum"
    assert captured["context"].roa_path is None
