# OpenCounsel: one-page brief

## Problem
Litigation filings fail on the last mile: formatting and pagination defects get e-filings rejected,
cite-checking and tables of authorities eat hours, AI-drafted citations have drawn sanctions, and
lawyers now owe courts and clients an account of how a filing was produced and what AI touched.
Sending client matter to a hosted model to fix any of this trades one risk for another.

## Solution
OpenCounsel turns a broken brief into a filing-ready, auditable package, locally. Two deterministic
passes (production, then source verification), immutable originals, a correction ledger for lawyer
review, and receipts for every step. On the modern stack it adds drained checks (a recurring check
becomes a rule served at $0), admission that cannot be argued with (fixed reads), and a "why did it
decide that" panel that lifts any decision to plain English, identically every time.

## Why now
Courts have sanctioned hallucinated citations (*Mata v. Avianca*, 2023) and issued AI-certification
orders; ABA Formal Opinion 512 (2024) sets duties of competence, confidentiality and supervision;
the EU AI Act's transparency duties are in force. Firms need the audit trail and the explanation,
not another chat window.

## Proof points
- An OpenAI Build Week finalist ("Turn a broken brief into a filing-ready, auditable package").
- Patent pending: a US provisional patent application filed by Stephen Schweizer (September 2026),
  "Recording reads beside stored results to control reuse and recomputation, and testing kept reads
  as a key against the answers owed". It is what lets a repeat check be served from a recorded rule
  with a receipt, and an explanation read the same way every time.
- Live receipts: the drain loop on our own workload (see `docs/img/drain-curve.svg`), the privilege
  gate on this repository, the two-pass Docker demonstration.
- A theorem table (see README, Proofs): unread_is_absent, explanation_faithful,
  explanation_idempotent, harvest_complete, served_memo_equals_model.

## Product line
One core (Nym, the organism, heal/spore) grows OpenCounsel, SVRF (the public merge train,
nybarius/SVRF), the drain, Meton-QS/Metonym, the nexus and the saga/MUD operator view. OpenCounsel is
the commercial flagship of that line.

## The ask
[operator to complete]
