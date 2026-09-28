"""Why did it decide that: the explanation lift over the correction ledger's own classes.

A ledgered correction is its class, ``(stage, item_type, application_status, review_status)`` (the
``Literal`` fields of :class:`opencounsel.contracts.models.CorrectionRecord`). Its plain-English
explanation is a presentation of that class assembled from fixed word tables, never generated: the
same class gives the same sentence (faithful), :func:`lower` parses the sentence back to its class
and :func:`explain_class` lifts it again to the same sentence (idempotent), and the witness is the
ledger note. The Lean statement is ``Institutional.ExplanationLift`` in
nexuspllc/institutional_stack (``explanation_faithful``, ``explanation_idempotent``,
``explanation_read_as_decision``).
"""

from __future__ import annotations

import re
from typing import Any

STAGES: tuple[str, ...] = ("proof", "cite-check", "hyperlink", "toc", "toa", "template")
ITEMS: tuple[str, ...] = (
    "correction",
    "record-citation",
    "authority-citation",
    "hyperlink",
    "toc-heading",
    "toa-authority",
    "toc-field",
    "toa-field",
)
APPLICATION: tuple[str, ...] = ("applied", "review-only")
REVIEW: tuple[str, ...] = ("pending", "accepted", "rejected")

_STAGE_WORDS = {
    "proof": "proofing",
    "cite-check": "cite-check",
    "hyperlink": "hyperlink",
    "toc": "table-of-contents",
    "toa": "table-of-authorities",
    "template": "template",
}
_ITEM_WORDS = {
    "correction": "a correction",
    "record-citation": "a record citation",
    "authority-citation": "an authority citation",
    "hyperlink": "a hyperlink",
    "toc-heading": "a table-of-contents heading",
    "toa-authority": "a table-of-authorities entry",
    "toc-field": "the table-of-contents field",
    "toa-field": "the table-of-authorities field",
}
_APPLICATION_WORDS = {"applied": "was applied", "review-only": "was flagged for review only"}
_REVIEW_WORDS = {
    ("applied", "pending"): "it stands unless a lawyer rejects it",
    ("applied", "accepted"): "a lawyer has accepted it",
    ("applied", "rejected"): "a lawyer has rejected it and it is reversed",
    ("review-only", "pending"): "it is not applied until a lawyer accepts it",
    ("review-only", "accepted"): "a lawyer has accepted it for application",
    ("review-only", "rejected"): "a lawyer has rejected it and it is not applied",
}
_STAGE_INV = {v: k for k, v in _STAGE_WORDS.items()}
_ITEM_INV = {v: k for k, v in _ITEM_WORDS.items()}
_APPLICATION_INV = {v: k for k, v in _APPLICATION_WORDS.items()}
_REVIEW_INV = {v: k for k, v in _REVIEW_WORDS.items()}
_PROSE = re.compile(r"^In the (.+?) pass, (.+?) (was .+?); (.+)\.$")

Cls = tuple[str, str, str, str]


def explain_class(cls: Cls) -> dict[str, Any]:
    """The lift of a class: its sentence, from the tables only."""
    stage, item, application, review = cls
    if (
        stage not in _STAGE_WORDS
        or item not in _ITEM_WORDS
        or application not in _APPLICATION_WORDS
        or (application, review) not in _REVIEW_WORDS
    ):
        raise ValueError(f"UNOBSERVED: not a ledger class: {cls!r}")
    prose = (
        f"In the {_STAGE_WORDS[stage]} pass, {_ITEM_WORDS[item]} "
        f"{_APPLICATION_WORDS[application]}; {_REVIEW_WORDS[(application, review)]}."
    )
    return {"class": cls, "prose": prose}


def explain_record(record: dict[str, Any]) -> dict[str, Any]:
    """The lift of a ledgered correction: its class's sentence, with the note as witness."""
    cls: Cls = (
        str(record.get("stage")),
        str(record.get("item_type", "correction")),
        str(record.get("application_status", "applied")),
        str(record.get("review_status", "pending")),
    )
    out = explain_class(cls)
    out["witness"] = str(record.get("note") or "")
    return out


def lower(prose: str) -> Cls | None:
    """The sentence back to its class; ``None`` when it is not a lifted sentence."""
    match = _PROSE.match(prose.strip())
    if not match:
        return None
    stage, item, application, review = match.groups()
    if (
        stage not in _STAGE_INV
        or item not in _ITEM_INV
        or application not in _APPLICATION_INV
        or review not in _REVIEW_INV
    ):
        return None
    app = _APPLICATION_INV[application]
    app_rev, rev = _REVIEW_INV[review]
    if app_rev != app:
        return None
    return (_STAGE_INV[stage], _ITEM_INV[item], app, rev)
