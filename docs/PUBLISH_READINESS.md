# Publish-readiness checklist

Nothing is published until the operator says so. Each line is a gate with its owner.

- [x] Privilege audit: the candidate uses an exact Git tree snapshot and the existing scanner.
      The current source tree is CLEAN after replacing the unconfirmed citation-year captions
      with manifested synthetic fixtures. Private history remains subject to its own review;
      it is never a parent of the candidate root.
- [x] Demo verified end to end on 2026-09-27 with `docker compose up --build --detach` (Compose v2
      plugin v5.5.1 installed in user space, pinned by the release sha256): the service reported
      `healthy`; `/healthz` returned `{"status":"ready"}`; `POST /api/demo` ran the public Dkt. 52
      demonstration to `completed` in about ten seconds: 8 pages, 10 TOC entries, 5 TOA authorities,
      31 formatting corrections applied, 5 review items, 4 source copies required, 1 hyperlink
      inserted; engine LibreOffice 25.2.3.2; output DOCX sha256 aa94f452...7f44683, PDF sha256
      857078bd...cd202c; artifacts: corrections, document, front-matter, original-pdf, package, pdf,
      publication, sources. The web app's own tests also pass (`uv run pytest tests/test_web_app.py`).
- [x] README opens with the value proposition and the finalist credential linked to OpenAI's
      announcement, then the buyer's problem, then the method and the patent, then the proofs, then
      the product line; OpenCounsel is named a Build Week finalist, never a winner.
- [x] Product-line links (SVRF, drain, heal/spore, Meton-QS, nexus, saga/MUD).
- [x] Pain-point map with cited public sources and no unsourced statistic (`docs/PAIN_POINTS.md`).
- [x] One-page brief with the ask left to the operator (`docs/BRIEF.md`).
- [x] Hand-authored SVGs (hero, filing pipeline, audit trail, decision to rule, product line, drain
      curve), no external services, readable in light and dark themes (`docs/img/`).
- [ ] Fresh public history: run `python3 scripts/build_public_candidate.py --root .
      --ref public/candidate --json` from an authenticated checkout after the gate. The first push
      has no parent; later updates parent only the observed candidate tip; unchanged trees do not
      push. Remote read failures, unfamiliar ancestry and non-fast-forward updates are refused.
      This stages a branch in the private repository and does not authorize public release.
- [ ] The operator's go.

## Excluded or listed for the operator's review

From `scripts/privilege_audit.py` at this head:

| item | where | why it is listed | proposed disposition |
|---|---|---|---|
| caption "Gems, Inc. v. Paul" | `tests/test_adapters.py` (tree and history) | was not in the manifest | operator-confirmed public (2026-09-27); now in `public_captions`, citation to be added |
| synthetic `OPENAI_API_KEY=sk-proj-...` and SSN | `tests/test_repository_privacy.py`, history blob | a synthetic fixture of the repository's own privacy test; matches the secret and PII patterns | operator-confirmed synthetic (2026-09-27); never ships in history: the public repository is regrown fresh; the fixture stays in the private tree as declared `synthetic_fixture_paths` |

The previously unconfirmed captions in the citation-year regression have been replaced with
existing manifested synthetic names. The years and assertions are unchanged. No new operator
confirmation is claimed. The candidate-builder refusal fixture is a scanner self-test containing
only generated marker strings, alongside the existing privilege-audit self-test.

Everything else the scanner matched is declared in the manifest: prose that discusses privilege
(`discussion_paths`), the `opencounsel.local` JSON-schema `$id` naming convention (`schema_id_hosts`),
and every case caption with its public source or its synthetic status.

## Candidate audit contract

The builder stages the worktree through a separate index and audits those exact tree bytes before
constructing the commit. It does not change the private branch or index. Only candidate refs below
`public/` are accepted; symlinks and submodules are refused. Nothing changes repository visibility,
creates a release, deploys the application, or merges the private development branch.

A REVIEW may proceed only when every item has an exact `operator_confirmed_reviews` entry in
`docs/LEGAL_FIXTURES.json`: `kind`, `path`, `where`, `witness`, the file's `sha256`,
`confirmed_by: "operator"`, and `confirmed_at`. Narrative historical confirmations do not authorize
new or changed bytes. REFUSED findings always stop the builder.

The conformance checks are included as `symbolic-ai-conformance.json` with `process.json` in both
review packages. A complete manifest supplies 3/7 bindings and 6/11 predicates; the report retains
all missing obligations and the donor's negative laws. These counts are evidence coverage, not
legal approval. CI runs the conformance and package tests through the existing pytest gate.
