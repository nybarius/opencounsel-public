from __future__ import annotations

from pathlib import Path

from starlette.testclient import TestClient

from opencounsel.web.app import create_app


def test_browser_exposes_complete_two_pass_controls(tmp_path: Path) -> None:
    with TestClient(create_app(root=tmp_path / "jobs")) as client:
        response = client.get("/")

    assert response.status_code == 200
    body = response.text
    assert 'name="record_mode"' in body
    assert 'value="no-record"' in body
    assert 'id="source-upload-form"' in body
    assert 'id="source-upload-list"' in body
    assert 'id="verify-sources"' in body
    assert 'id="link-review"' in body
    assert 'id="link-list"' in body
    assert 'id="approve-links"' in body
    assert 'id="download-final-package"' in body
    assert 'id="download-linked-document"' in body
    assert 'id="download-linked-pdf"' in body
    assert 'id="preview-before"' in body
    assert 'id="preview-prepared"' in body
    assert 'id="download-original-pdf"' in body


def test_browser_script_calls_source_and_link_finalization_endpoints() -> None:
    script = Path("src/opencounsel/web/static/app.js").read_text(encoding="utf-8")

    assert "authority_id" in script
    assert "source-upload-form" in script
    assert "link_ids" in script
    assert "/sources`" in script
    assert "/links`" in script
    assert '"original-pdf"' in script
    assert "showPreview" in script
