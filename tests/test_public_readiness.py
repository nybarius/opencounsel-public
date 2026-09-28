"""RED: the public-readiness contract of the OpenCounsel repository.

The README opens with the buyer's problem in plain English, then the method and the patent, then the
proofs, then the product line; OpenCounsel is a Build Week finalist, never a winner; the pain-point
map cites public sources and carries no unsourced statistic; the brief is one page with the ask left
to the operator; the graphics are hand-authored SVGs readable in light and dark themes; the
publish-readiness checklist and the gap report exist; the privilege gate is part of the development
gate.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_readme_opens_with_the_buyers_problem_then_method_proofs_product_line() -> None:
    text = _read("README.md")
    heads = [m.group(1).strip() for m in re.finditer(r"^## (.+)$", text, re.M)]
    order = [
        next(i for i, h in enumerate(heads) if key in h.lower())
        for key in ("problem", "method", "proof", "product line")
    ]
    assert order == sorted(order), heads
    # The credential links to OpenAI's announcement; its URL slug is not a claim about us.
    prose = text.lower().replace("developers.openai.com/blog/build-week-winners", "")
    assert "finalist" in prose and "winner" not in prose
    assert "provisional" in text.lower() and "SchweizerMethod" in text
    assert "nybarius/SVRF" in text and "Why did it decide that" in text


def test_pain_point_map_cites_public_sources_and_carries_no_unsourced_number() -> None:
    text = _read("docs/PAIN_POINTS.md")
    for source in ("Mata v. Avianca", "Formal Opinion 512", "Regulation (EU) 2024/1689", "1002.9"):
        assert source in text, source
    rows = [line for line in text.splitlines() if line.startswith("| ") and "---" not in line]
    assert len(rows) >= 8
    for line in rows[1:]:
        cells = [c.strip() for c in line.strip("|").split("|")]
        assert len(cells) >= 5 and cells[-1], line  # every pain has a cited source cell
    assert not re.search(r"\b\d{2,3}%", text)  # no unsourced percentage anywhere


def test_the_brief_is_one_page_with_the_ask_left_to_the_operator() -> None:
    text = _read("docs/BRIEF.md")
    assert len(text.splitlines()) <= 80
    for section in ("Problem", "Solution", "Why now", "Proof points", "Product line", "The ask"):
        assert section in text, section
    assert "finalist" in text.lower() and "winner" not in text.lower()
    assert "[operator to complete]" in text


def test_graphics_are_hand_authored_svgs_readable_in_both_themes() -> None:
    for name in ("filing-pipeline", "decision-to-rule", "drain-curve", "product-line"):
        svg = _read(f"docs/img/{name}.svg")
        assert svg.lstrip().startswith("<svg") and "currentColor" in svg
        # no external services
        assert "http://" not in svg.replace("http://www.w3.org", "") and "https://" not in svg
    assert "our own workload" in _read("docs/img/drain-curve.svg").lower()


def test_readiness_checklist_gap_report_and_gate() -> None:
    check = _read("docs/PUBLISH_READINESS.md")
    for item in (
        "privilege audit",
        "demo verified",
        "patent",
        "finalist",
        "product line",
        "fresh public history",
        "excluded",
    ):
        assert item in check.lower(), item
    gap = _read("docs/GAP_REPORT.md")
    for word in ("symbolic-ai", "drain", "heal", "spore", "Meton", "SVRF", "unread_is_absent"):
        assert word in gap, word
    assert "privilege_audit.py" in _read("README.md")


def test_the_ui_onboards_and_the_why_panel_carries_the_receipt() -> None:
    html = _read("src/opencounsel/web/static/index.html")
    assert 'id="onboarding"' in html and "Three steps" in html
    for step in ("Run the OpenAI filing demo", "Review items", "Why did it decide that"):
        assert step in html, step
    js = _read("src/opencounsel/web/static/app.js")
    assert "process_id" in js and "correction_id" in js  # the receipt beside every explanation
    assert "docs/PUBLISH_READINESS.md" in _read("README.md")

