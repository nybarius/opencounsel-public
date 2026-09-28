# Gap report: symbolic-ai and OpenCounsel against the modern stack

Measured on 2026-09-27 with institutional_stack's readers (`tools/nym_ingest.py`) and the Prometheus
cut of each repository (`tools/prometheus_cuts.py`, `tools/organism_rebuild.py`).

## What exists

| repository | paths | bytes | lowered into Nym (file level) | determinations | digestion classes | Prometheus cut (grown from the spore) |
|---|---:|---:|---:|---|---:|---|
| OpenCounsel (`2c350f4`) | 162 | 1,381,447 | 73% of bytes | python 1,019; markdown 149; js 24 | 587 | 81 paths, 569,413 bytes, 521 keys |
| symbolic-ai (`a450984`) | 561 | 7,540,241 | 84% of bytes | markdown 3,147; python 3,070; json 58 | 1,850 | 35 paths, 255,197 bytes, 211 keys |

The unread remainder is lockfiles, css/html and PDFs, not source. 21 of 5,401 digestion keys are
shared across the five Prometheus cuts (institutional_stack-opencounsel 8, -counterexample 7,
-symbolic_ai 5): the first cross-product method-capital number.

## What the modern stack replaces, absorbs, or adds

| area | OpenCounsel / symbolic-ai today | modern stack | disposition |
|---|---|---|---|
| Deterministic passes, immutable originals, receipts | OpenCounsel's two passes, correction ledger, hash records | the same, now as cells of the organism round with receipts consumed by `record` | absorbed as is |
| Legal semantics: witnessed state, support, attacks, defeat, debt | symbolic-ai's proof/procedure/precedent/adjudication packages | lowered into Nym digestion classes (1,850) so a check is a class the drain can serve | absorbed by lowering; nothing rewritten by hand |
| Model calls | none in OpenCounsel (local-first); symbolic-ai's research loops | the drain loop: a recurring question becomes a rule served at $0; free pairs name the missing read | new |
| "Why did it decide that" | reports and ledgers | the explanation lift (`ExplanationLift`): idempotent, faithful plain English from the class | new |
| Admission | development gate (ruff, mypy, pytest, uv build) | admission under fixed reads (replay, suites, dispositions, intake) and receipts; SVRF as the merge train | replaces the hand gate |
| Self-repair and recovery | none | heal (every level of the organism is incidence read by a cell) and the spore (the minimum recoverable organism, pushed off-host) | new |
| Operator surface | the loopback web UI and CLI | Meton-QS / Stagehand MCP as the operator surface; the saga and MUD; the nexus controls | new |
| Confidentiality boundary | disabled network and model policies | the same, plus `unread_is_absent`: a read the demand does not consume is absent from the cut | strengthened, with a theorem |
| Publication | all rights reserved, private | the privilege gate (`scripts/privilege_audit.py`) and a fresh public history by spore regrow | new |

## What is still open

- The C10 conformance adapter is wired into OpenCounsel's review packages: the persisted process
  manifest supplies 3/7 bindings and 6/11 predicates of the pinned donor vocabulary. Missing
  obligations remain explicit. This is a data-only conformance donor, not full symbolic-ai
  reasoning or domain admission. The review package retains both the manifest and its checks.
- The earlier Compose demo receipt remains in `docs/PUBLISH_READINESS.md`. Current gate results
  and remaining execution limits are recorded in `docs/PROJECT_STATE.md`.
