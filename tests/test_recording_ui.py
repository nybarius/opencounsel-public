from __future__ import annotations

from pathlib import Path

from lxml import html
from starlette.testclient import TestClient

from opencounsel.web.app import create_app
from opencounsel.web.jobs import JobManager


def test_home_prioritizes_real_openai_demo_and_explains_four_stage_flow(
    tmp_path: Path,
) -> None:
    manager = JobManager(tmp_path / "jobs")
    with TestClient(create_app(manager=manager)) as client:
        response = client.get("/")

    assert response.status_code == 200
    page = response.text
    assert "Turn a broken brief into a filing-ready package" in page
    assert "The New York Times Company v. Microsoft Corporation" in page
    assert "Run the OpenAI filing demo" in page
    assert 'id="demo-button"' in page
    assert 'class="button primary demo-cta"' in page
    assert 'aria-label="Demo workflow"' in page
    assert page.index("Prepare") < page.index("Review sources")
    assert page.index("Review sources") < page.index("Approve links")
    assert page.index("Approve links") < page.index("Download package")
    assert "Malformed DOCX" in page
    assert "Linked TOC and TOA" in page
    assert "Four public opinions" in page
    assert "Hash-bound final ZIP" in page


def test_recording_ui_assets_include_demo_and_stage_components(tmp_path: Path) -> None:
    manager = JobManager(tmp_path / "jobs")
    with TestClient(create_app(manager=manager)) as client:
        css = client.get("/assets/recording.css").text

    assert ".demo-stage-rail" in css
    assert ".transformation-card" in css
    assert ".demo-cta" in css


def test_results_close_with_brief_filing_workload_scale() -> None:
    page = Path("src/opencounsel/web/static/index.html").read_text(encoding="utf-8")
    document = html.fromstring(page)
    workspace = document.xpath(
        '//*[@id="results-view"]/*[contains(concat(" ", @class, " "), " workspace-card ")]'
    )[0]
    scale_matches = document.xpath('//*[@id="national-filing-scale"]')
    assert len(scale_matches) == 1
    scale = scale_matches[0]
    assert workspace.getnext() is scale
    assert scale.getnext() is None

    for expected in (
        "BRIEF FILING SCALE",
        "Every brief filing requires professional production before it can be served or filed",
        "Formatting, pagination, TOC and TOA, citation links, source checks, and final publication",
        "3.5 reclaimed hours \N{MULTIPLICATION SIGN} $200 = $700 per filing package",
        "100,000 annual brief filings",
        "$70 million",
        "250,000 annual brief filings: $175 million",
        "500,000 annual brief filings: $350 million",
        (
            "The model counts filing packages—the documents that must actually be formatted, "
            "checked, linked, reviewed, and published."
        ),
        "Unit value: 3.5 hours \N{MULTIPLICATION SIGN} $200 = $700 per filing package",
        "Scope: brief filing packages requiring production and review",
        (
            "Work included: formatting, front matter, authority handling, source verification, "
            "and publication"
        ),
        "Scenario A: 100,000 \N{MULTIPLICATION SIGN} $700 = $70,000,000",
        "Scenario B: 250,000 \N{MULTIPLICATION SIGN} $700 = $175,000,000",
        "Scenario C: 500,000 \N{MULTIPLICATION SIGN} $700 = $350,000,000",
    ):
        assert expected in page

    for excluded in (
        "16.8 million civil cases",
        "16.48 million state civil cases",
        "303,563 federal district civil cases",
        "$587 million",
        "$1.17 billion",
        "no comprehensive national count",
        "not a measured national brief count",
    ):
        assert excluded not in page

    assert "<summary>Methodology</summary>" in page
