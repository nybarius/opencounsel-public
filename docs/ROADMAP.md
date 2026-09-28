# Practice-driven roadmap

Updated: 2026-07-20

OpenCounsel should earn its keep as a private practice instrument before it attempts platform breadth. Until the OpenAI Build Week submission is filed, the governing cut line is one honest, visually legible, locally installable two-pass demonstration.

## Build Week critical path

```text
real public brief reconstructed as malformed DOCX
    -> filing-profile preparation
    -> professional DOCX/PDF + linked TOC/TOA + audit and acquisition reports
    -> user uploads declared public authority PDFs
    -> deterministic identity and quotation verification
    -> explicit durable-link approval
    -> final linked filing/review package
```

### Phase 1 — real-filing fixture and publication gate

Status: complete and merged in PR `#16`.

The demo matter is derived from OpenAI Defendants' public February 26, 2024 motion to dismiss in *The New York Times Company v. Microsoft Corporation*, S.D.N.Y. No. 23-cv-11195, Dkt. 52. The fixture preserves a Word-native, matter-specific SDNY caption, the core argument hierarchy, selected real authorities, and provenance, and deliberately removes completed production work while introducing visible formatting defects.

Acceptance completed:

- one empty TOC slot and one empty TOA slot;
- display-oriented `openai-mtd-deformatted.docx` plus canonical private processing paths;
- `demo-source.json` with filing provenance and transformation description;
- four local public-authority source PDFs for the second pass;
- unchanged strict LibreOffice TOC/TOA reconciliation; and
- CI run `458` green across 231 tests, coverage, Ruff, mypy, package build, Windows contracts, real LibreOffice publication, style review, and release-container checks.

The recorded motion-to-dismiss story uses the explicit no-record path. The synthetic searchable record remains only for record-backed regression coverage.

### Phase 2 — recording-grade browser experience

Status: complete and merged in PR `#18` as commit `793c9d1`.

Delivered experience:

1. The opening state immediately states the transformation: broken brief to filing-ready package.
2. The public OpenAI filing demo is identified by matter and Dkt. 52.
3. `Run the OpenAI filing demo` is the prominent primary action; manual upload is secondary.
4. A visible four-stage rail presents Prepare, Review sources, Approve links, and Download package.
5. Before-and-after document cards show the malformed source, linked TOC/TOA, verified public opinions, and hash-bound final ZIP.
6. Existing result, source-upload, link-review, PDF-preview, audit, deletion, accessibility, and error surfaces remain intact.
7. All fonts and UI assets remain local; no CDN or JavaScript build pipeline was added.

The implementation retains Starlette, the existing local job manager, semantic HTML, modern CSS, and minimal browser JavaScript. Observable homepage behavior was introduced through committed RED tests before implementation. Exact-head CI run `509` passed the full release gate before merge.

### Phase 3 — one-command local installation

Status: complete and merged in PR `#23` as commit `16b570b`.

Required command:

```bash
docker compose up --build
```

No host Python, PostgreSQL, LibreOffice, credentials, manual volume creation, or package installation is required.

Delivered installation contract:

- stable Compose project name `opencounsel`;
- loopback-only `127.0.0.1:8765` host binding;
- named `opencounsel-data` workspace volume;
- init handling and explicit `/healthz` readiness declaration;
- retained non-root, read-only, capability-dropped, no-new-privileges release posture;
- README instructions for start, `healthy` verification, the public demo, retained-data shutdown, and complete volume removal; and
- executable tests pinning the Compose and operator contract.

A prebuilt registry image, native signed installer, and hosted deployment remain post-submission work.

### Phase 4 — Codex hardening, capture, and submit

Status: engineering complete locally; human capture and submission remain.

The primary Codex session preserved and diagnosed the real publication failure, committed a regression and principled fix, repaired the clean-rehearsal integration defects exposed afterward, added an explicit eligible-link approval to the public demo, verified the complete two-pass Docker workflow, ran the project gate with real LibreOffice, added the compact national filing-scale close, and reconciled release documentation.

Bounded clean-context documentation work from PRs `#26` and `#27` was inspected and selectively integrated. The session-to-commit map is in [`DEVELOPMENT_PROVENANCE.md`](DEVELOPMENT_PROVENANCE.md).

Completed release deliverables:

- complete exact-head release gate after final hardening;
- clean Docker-state rehearsal of both passes;
- first-pass artifacts confirmed byte-identical after finalization;
- job deleted through the UI and local matter artifacts confirmed removed;
- final Devpost narrative and setup instructions;
- documented provenance distinguishing ChatGPT Work, primary Codex, and bounded clean contexts; and
- primary Codex `/feedback` session ID preserved in that provenance record.

Remaining human deliverables:

- public YouTube video shorter than three minutes;
- three screenshots: malformed intake, professional first pass, and verified final package;
- public repository licensing or private-repository reviewer access; and
- final privacy review confirming that only public filing material and generated support files appear.

The recorded sequence must execute both processing passes live. Prepared public authority PDFs are permitted; canned job JSON, mocked progress, client material, publisher credentials, and hidden precomputed results are not.

## Submission acceptance gate

- Fresh Docker installation reaches `/healthz` and completes the Dkt. 52-derived demonstration.
- The malformed input is visibly different from the professional output.
- The input DOCX remains byte-identical and every derived artifact is hash-bound to it.
- The prepared filing has correct typography, hierarchy, linked TOC/TOA, Roman front matter, Arabic body pagination, and verified eligible links.
- Pass one identifies exact requested source copies without calling detected authorities missing.
- Pass two rejects mismatched or undeclared sources, verifies declared source identity and exact quotations, and leaves characterization for lawyer review.
- The final ZIP contains the DOCX/PDF pair, correction and publication manifests, source and link reports, authority package, verification report, and hashes.
- Linux, Windows-contract, real-LibreOffice, package-build, and release-container gates are green on the exact submitted commit.
- The development narrative, session map, commit graph, and pull-request history agree.
- The complete story fits comfortably inside the video limit without accelerated or misleading footage.

## Submission cut line

Defer until after submission:

- accounts, hosting, billing, telemetry, chat, or multi-matter dashboards;
- OCR or arbitrary image-only filings;
- automated Lexis or Westlaw login, scraping, or session-link use;
- model-based characterization approval;
- additional court profiles or judge overlays;
- prebuilt registry images and native installers;
- generalized WorkProductIR round trips; and
- unrelated practice-management features.

When schedule pressure arises, preserve the truthful two-pass path and remove optional polish. Never weaken verification, substitute canned outputs, or imply that source identity proves a legal characterization.

## Post-submission product roadmap

1. Record-citation workbench with review rows, physical-page resolution, context, warnings, and direct page access.
2. Front-matter and filing-profile expansion through reviewed templates and court or judge overlays.
3. Verified authority and proposition support with point-in-time law and model-assisted characterization kept separate from deterministic identity and quote checks.
4. Word and filing IR with reviewed-Word reconciliation and cross-renderer identity proofs.
5. Binder and practice control plane connecting stable filing provenance to mail, tasks, deadlines, procedures, privilege review, and precedent atoms.

## Do not repeat

- Do not reintroduce Aspose or dependence on Microsoft Word field updates.
- Do not place client-derived names, prose, metadata, hashes, or geometry in Git.
- Do not expose sensitive material in contest-facing ChatGPT or Codex sessions.
- Do not treat a publisher PDF or embedded URL as verified durable navigation.
- Do not call requested source copies missing authorities.
- Do not let UI-framework enthusiasm create a second runtime or obscure the local-first trust story.
- Do not expand breadth before the submission artifact is recorded and filed.
