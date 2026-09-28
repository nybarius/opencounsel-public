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
- A US provisional patent application (NexusPL LLC, filed September 2026) on the method: consumer-
  relative substitution over finite incidence presentations, the SchweizerMethod, which is what makes
  a check drainable into a rule and an explanation canonical.
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
