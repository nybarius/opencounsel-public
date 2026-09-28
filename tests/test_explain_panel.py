"""RED: "why did it decide that" -- the explanation lift over the correction ledger's own classes.

A ledgered correction is its class: (stage, item_type, application_status, review_status). Its
plain-English explanation is a presentation of that class from fixed word tables, never generated:
the same class gives the same sentence (faithful), lowering the sentence gives back the class and
re-lifting gives the same sentence (idempotent), and the witness is the ledger note. The web app
serves it at `/api/explain` and the review has a "Why did it decide that" panel.
"""

from __future__ import annotations

from starlette.testclient import TestClient

from opencounsel import explain as ex
from opencounsel.web.app import create_app

RECORD = {
    "stage": "cite-check",
    "item_type": "authority-citation",
    "application_status": "review-only",
    "review_status": "pending",
    "note": "Reporter volume does not match the uploaded opinion.",
    "original_text": "550 U.S. 554",
    "replacement_text": "550 U.S. 544",
}


def test_the_lift_is_faithful_and_idempotent() -> None:
    e = ex.explain_record(RECORD)
    assert e["class"] == ("cite-check", "authority-citation", "review-only", "pending")
    assert e["prose"] == (
        "In the cite-check pass, an authority citation was flagged for review only; "
        "it is not applied until a lawyer accepts it."
    )
    assert e["witness"] == "Reporter volume does not match the uploaded opinion."
    assert ex.lower(e["prose"]) == e["class"]
    assert ex.explain_class(ex.lower(e["prose"]))["prose"] == e["prose"]
    other = dict(RECORD, note="another note", original_text="x", replacement_text="y")
    assert ex.explain_record(other)["prose"] == e["prose"]
    applied = dict(RECORD, stage="toa", item_type="toa-authority", application_status="applied")
    assert ex.explain_record(applied)["prose"] != e["prose"]
    assert ex.explain_record(applied)["prose"] == (
        "In the table-of-authorities pass, a table-of-authorities entry was applied; "
        "it stands unless a lawyer rejects it."
    )


def test_every_ledger_class_lifts_deterministically() -> None:
    seen = {}
    for stage in ex.STAGES:
        for item in ex.ITEMS:
            for app in ex.APPLICATION:
                for rev in ex.REVIEW:
                    cls = (stage, item, app, rev)
                    prose = ex.explain_class(cls)["prose"]
                    assert ex.lower(prose) == cls, prose
                    assert prose not in seen or seen[prose] == cls
                    seen[prose] = cls


def test_the_api_serves_the_lift_and_the_ui_has_the_panel() -> None:
    client = TestClient(create_app())
    response = client.post("/api/explain", json=RECORD)
    assert response.status_code == 200
    body = response.json()
    assert body["prose"].startswith("In the cite-check pass") and body["witness"] == RECORD["note"]
    assert body["class"] == ["cite-check", "authority-citation", "review-only", "pending"]
    bad = client.post("/api/explain", json={"stage": "nonsense"})
    assert bad.status_code == 400 and "UNOBSERVED" in bad.json()["error"]
    home = client.get("/").text
    assert 'id="why-tab"' in home and "Why did it decide that" in home
    assert "/api/explain" in client.get("/assets/app.js").text
