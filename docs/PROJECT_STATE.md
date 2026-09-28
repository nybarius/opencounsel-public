# OpenCounsel project state

Updated: 2026-09-28

- Current tranche: PR #1, public-candidate CI repair plus publication-state reconciliation.
- Public `main` was red because `git commit-tree` inherited Git identity from the host; clean
  GitHub runners have no such identity, so four candidate-builder tests failed with exit 128.
- RED is retained in commit `e0416662`: the new regression clears HOME and all Git author/committer
  environment and requires the builder to supply its own candidate identity.
- The first implementation was reverted after the privilege scanner correctly rejected a literal
  private-host marker in production source.
- Current implementation `d69f3045` constructs the same non-secret candidate identity without a
  scanner-visible private-host literal.
- GitHub push CI for `d69f3045` is GREEN: full pytest/coverage, Ruff, mypy, build, style packet,
  Windows contracts, and the clean-state Compose rehearsal all passed.
- The candidate builder still audits the exact staged tree, preserves the private head and index,
  permits only `public/` refs, refuses symlinks and unknown ancestry, and never force-pushes.
- The public repository is now described as public. Stale language saying publication still awaited
  operator authorization has been removed.
- The demonstrated product remains local-first and single-user; public source visibility does not
  imply hosted client-matter processing.
- No license is granted for OpenCounsel at this head; the repository remains proprietary unless an
  actual license is committed later.
- Existing public proof point remains the 2026-09-27 clean Compose demo: 8 pages, 10 TOC entries,
  5 TOA authorities, 31 formatting corrections, and 5 review items in about ten seconds.
- Do not weaken the privilege audit to make a release pass; change the candidate bytes or declare
  exact manifested synthetic/public evidence instead.
- Do not rely on developer-global Git configuration for candidate-history construction.
- Next action: merge PR #1 only after this documentation-only head receives the same green CI gate.
