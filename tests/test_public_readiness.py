"""RED: the public-readiness contract of the OpenCounsel repository.

OpenCounsel reads as a freestanding product. The README opens with the buyer's problem in plain
English, then the method and the patent (plain English, the actual filer, the provisional's title
quoted), then the contact; neither the README, the one-page brief nor any doc the README links
refers to a wider product line, its internal components or a theorem library. OpenCounsel is a
Build Week finalist, never a winner; the pain-point map cites public sources and carries no
unsourced statistic; the brief is one page and ends with a contact line; the graphics are
hand-authored SVGs readable in light and dark themes; the publish-readiness checklist exists; the
privilege gate is part of the development gate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# References to the wider line that a freestanding OpenCounsel page must not carry.
_LINE_REFERENCES = (
    r"\bNym\b",
    r"\b[Oo]rganism",
    r"\b[Ss]pore",
    r"\b[Hh]eal\b",
    r"\b[Dd]rain",
    r"\bSVRF\b",
    r"\bMeton",
    r"\b[Nn]exus\b",
    r"\b[Ss]aga\b",
    r"\bMUD\b",
    r"institutional_stack",
    r"formal/Institutional",
    r"\bLean\b",
    r"\b[Tt]heorem",
    r"[Pp]roduct[ -]line",
    r"SchweizerMethod",
    r"finite incidence presentations",
    r"operator to complete",
)


def _public_docs() -> list[str]:
    readme = _read("README.md")
    linked = sorted(set(re.findall(r"\]\((docs/[^)#]+\.(?:md|json))\)", readme)))
    return ["README.md", "docs/BRIEF.md", *linked]


def test_readme_opens_with_the_buyers_problem_then_the_method_then_contact() -> None:
    text = _read("README.md")
    heads = [m.group(1).strip() for m in re.finditer(r"^## (.+)$", text, re.M)]
    order = [
        next(i for i, h in enumerate(heads) if key in h.lower())
        for key in ("problem", "method", "contact")
    ]
    assert order == sorted(order), heads
    # The credential links to OpenAI's announcement; its URL slug is not a claim about us.
    prose = text.lower().replace("developers.openai.com/blog/build-week-winners", "")
    assert "finalist" in prose and "winner" not in prose
    # The patent note is plain English, names the actual filer and quotes the provisional's title.
    assert "provisional" in text.lower() and "Stephen Schweizer" in text
    assert "Recording reads beside stored results" in text
    assert "Why did it decide that" in text
    assert "stephen.schweizer [at] gmail [dot] com" in text


# A dated operator confirmation is a historical record: it keeps its exact bytes and is not scanned.
_HISTORICAL_CONFIRMATIONS = {"docs/LEGAL_FIXTURES.json": ("2026-09-27",)}


def _scannable(rel: str) -> str:
    body = _read(rel)
    dates = _HISTORICAL_CONFIRMATIONS.get(rel)
    if dates:
        manifest = json.loads(body)
        for date in dates:
            manifest["operator_confirmed"].pop(date)
        body = json.dumps(manifest)
    return body


def test_public_docs_are_freestanding() -> None:
    for public in _public_docs():
        body = _scannable(public)
        for pattern in _LINE_REFERENCES:
            assert not re.search(pattern, body), (public, pattern)
        assert not re.search(r"provisional[^.]*NexusPL|NexusPL[^.]*provisional", body), public
        assert not re.search(r"[A-Za-z0-9._%+-]+@gmail\.com|mailto:", body), public


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


def test_the_brief_is_one_page_and_ends_with_a_contact_line() -> None:
    text = _read("docs/BRIEF.md")
    assert len(text.splitlines()) <= 80
    for section in ("Problem", "Solution", "Why now", "Proof points", "Contact"):
        assert section in text, section
    assert "finalist" in text.lower() and "winner" not in text.lower()
    assert "Stephen Schweizer" in text and "Recording reads beside stored results" in text
    assert "stephen.schweizer [at] gmail [dot] com" in text


def test_graphics_are_hand_authored_svgs_readable_in_both_themes() -> None:
    for name in ("hero", "filing-pipeline", "audit-trail", "decision-to-rule"):
        svg = _read(f"docs/img/{name}.svg")
        assert svg.lstrip().startswith("<svg") and "currentColor" in svg
        # no external services
        assert "http://" not in svg.replace("http://www.w3.org", "") and "https://" not in svg
        for pattern in _LINE_REFERENCES:
            assert not re.search(pattern, svg), (name, pattern)
    for retired in ("product-line", "drain-curve"):
        assert not (ROOT / f"docs/img/{retired}.svg").exists(), retired


def test_readiness_checklist_and_gate() -> None:
    check = _read("docs/PUBLISH_READINESS.md")
    for item in (
        "privilege audit",
        "demo verified",
        "patent",
        "finalist",
        "fresh public history",
        "excluded",
    ):
        assert item in check.lower(), item
    assert "privilege_audit.py" in _read("README.md")


def test_the_ui_onboards_and_the_why_panel_carries_the_receipt() -> None:
    html = _read("src/opencounsel/web/static/index.html")
    assert 'id="onboarding"' in html and "Three steps" in html
    for step in ("Run the OpenAI filing demo", "Review items", "Why did it decide that"):
        assert step in html, step
    js = _read("src/opencounsel/web/static/app.js")
    assert "process_id" in js and "correction_id" in js  # the receipt beside every explanation
    assert "docs/PUBLISH_READINESS.md" in _read("README.md")
