# OpenCounsel project state

Updated: 2026-09-27

- Last completed tranche: PR #35 (conformance donor contracts, audited candidate-history builder,
  onboarding with receipts beside explanations).
- The inherited RED tests are implemented: pinned symbolic-ai donor contracts, exactly 3/7
  supplied bindings and 6/11 supplied predicates, audited candidate-history builder, and
  three-step onboarding with process/correction receipts beside explanations.
- The candidate test had queried an absent remote inside its bare fixture. The test-only
  correction reads the bare repository's refs directly and still requires them to be empty.
  Other edits to inherited assertions are formatting only.
- A second committed RED/GREEN pair validates donor identities and manifest fields, rejects
  invalid evidence, attaches `process.json` and `symbolic-ai-conformance.json` to downloadable
  first-pass and final review packages, and binds operator review to exact file bytes.
- The current source-tree audit is CLEAN. The citation-year regression uses manifested
  synthetic captions with the same years and assertions. No new operator confirmation is
  claimed. The candidate refusal fixture is included with the scanner's synthetic self-tests.
- Required local gate passes: lock check; Ruff; mypy (72 source files); pytest (289 passed,
  1 optional PostgreSQL test skipped, 90.21% coverage); wheel/sdist build; style-review generation.
  JavaScript syntax and 33 focused C10/audit tests pass. The full suite used the runtime's
  LibreOfficeDev 26.8 renderer through a local executable wrapper. No Docker rehearsal was
  performed in this tranche; the earlier Compose receipt remains in PUBLISH_READINESS.md.
- GitHub push and PR CI at `f44ec44cc236f383f8d39e55290b173b71ff1f2f` ended in failure before
  downloadable job logs were available. Local results do not replace those remote outcomes.
- `scripts/build_public_candidate.py` snapshots through a separate index, audits the exact
  Git tree, and permits only `public/` candidate refs. The first commit is parentless; later
  commits parent only the observed candidate tip. An unchanged tree does not push. Remote
  failures, unknown ancestry, symlinks and non-fast-forward updates are refused.
- Candidate staging does not publish the repository. Do not change visibility, create a
  release, deploy, merge #35, or treat conformance field coverage as legal approval.
