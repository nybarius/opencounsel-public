# OpenAI Build Week submission kit

Updated: 2026-07-21

This file is the recording and submission handoff for OpenCounsel. Public materials may show only the
public Dkt. 52 filing derivative and generated support files committed for the demonstration. Never show
client material, publisher credentials, private matters, personal browser data, or unreviewed downloads.

## Submission settings

- **Track:** Work & Productivity
- **Project name:** OpenCounsel
- **Tagline:** Turn a broken brief into a filing-ready, auditable package.
- **Repository:** `nybarius/OpenCounsel`
- **Runtime:** Local Python 3.12 browser application distributed with Docker
- **Publication engine:** LibreOffice behind a deterministic publication adapter
- **Demo matter:** OpenAI Defendants' February 26, 2024 Dkt. 52 motion to dismiss in
  *The New York Times Company v. Microsoft Corporation*, reconstructed from the public filing

The submission deadline is July 21, 2026 at 5:00 p.m. Pacific. The demo must be a public YouTube video
shorter than three minutes. The repository must either be public with an actual license or remain private
and be shared with the required Devpost reviewers.

## Submission description

OpenCounsel automates the expensive, error-prone last mile of legal briefing. A lawyer supplies a Word
filing and either a validated record package or an explicit no-record declaration. OpenCounsel preserves
the source, applies court typography and hierarchy, compiles linked tables of contents and authorities,
identifies exact authority source copies needed for review, publishes DOCX and PDF through LibreOffice,
and returns hash-bound correction, publication, source, link, and verification reports.

The second pass is deliberately honest. Requested opinion PDFs are uploaded into stable authority-ID
slots. OpenCounsel rejects mismatched, undeclared, duplicate, malformed, encrypted, symlinked, and
oversized inputs. It verifies source identity and exact quotations deterministically. It classifies
embedded PDF links separately and requires explicit approval before inserting eligible durable links.
Whether a case supports a legal characterization remains lawyer judgment.

The product is local-first. Deterministic code owns provenance, pagination, semantic entries, locators,
links, validation, and artifact hashes. It does not send client prose to a hosted model, scrape licensed
publishers, overwrite the original, or claim that navigation evidence proves a proposition.

## Development provenance

Initial architecture and implementation were developed during the contest period with GPT-5.6
through ChatGPT Work. The submitted Codex session served as the principal contest-finalization and
release-engineering thread: it forensically diagnosed the retained LibreOffice failure, committed the
regression and fix separately, repaired clean-rehearsal integration contracts, ran the full two-pass
Docker and project gates, added the bounded recording close, and prepared this release.

Bounded clean-context work produced PRs `#26` and `#27`; this primary session reviewed them and
selectively integrated compatible documentation. The repository history is the authoritative record,
and the submission must not imply that one transcript authored every line. See
[`DEVELOPMENT_PROVENANCE.md`](DEVELOPMENT_PROVENANCE.md) for the commit map.

## What is working

- DOCX plus mapped ROA ZIP, attested searchable record PDF, or explicit no-record intake
- New York filing profile with deterministic typography and heading normalization
- Linked, correctly paginated TOC and categorized TOA
- Roman front matter followed by Arabic body pagination
- Terminal DOCX/PDF publication and hash-bound first-pass package
- Stable authority upload slots and fail-closed source intake
- Deterministic source identity and exact-quotation checks
- One prepared eligible durable link, explicit approval, and separate linked artifacts
- Final review ZIP preserving first-pass immutability
- Recording-grade local browser interface and complete job deletion
- Non-root, loopback-only, read-only, capability-dropped Docker runtime with LibreOffice included
- Linux, coverage, Ruff, mypy, real-LibreOffice, package, platform-independent Windows-contract, and
  container gates

## Known boundaries

- Scanned or irregularly numbered records require OCR or a mapped record package first.
- Authority links are navigation, not substantive verification.
- Characterization review remains with counsel.
- The current product is a private, local, single-user demonstration, not a hosted multi-matter system.
- The repository is all-rights-reserved unless an actual license is selected and committed.
- Reviewed-Word reconciliation, additional court profiles, hosted deployment, registry images, and native
  installers remain post-submission work.

## Under-three-minute demo

Target length: **2:47-2:59**. Execute both passes live. Prepared public authority PDFs are permitted;
canned job JSON, mocked progress, hidden precomputed results, client material, or publisher sessions are
not.

### 0:00-0:15 — The broken filing

Show `openai-mtd-deformatted.docx` briefly in Word: mixed typography, broken hierarchy, placeholder front
matter, and poor pagination.

> The legal argument exists, but the filing product does not. A lawyer still has to normalize the Word
> document, compile and paginate the tables, identify authority source copies, verify them, and assemble
> a reviewable package.

### 0:15-0:30 — Local product

Show the running Docker service and the OpenCounsel intake page. Do not record the image build.

> OpenCounsel runs locally in one locked-down container. It needs no host Python, database, LibreOffice
> installation, publisher account, or upload to a hosted legal service.

### 0:30-0:50 — One-click public demo

Point to the public matter line, malformed-to-filing-ready card, and four-stage rail. Click
**Run the OpenAI filing demo**.

> This demonstration uses a privacy-safe reconstruction of OpenAI's publicly filed Dkt. 52 motion. The
> recorded story uses the explicit no-record path because this motion has no material record citations.

### 0:50-1:15 — Live first pass

Show the real progress stages advancing.

> The pipeline preserves the source, applies the filing profile, compiles linked front matter, publishes
> through LibreOffice, validates the result, and reports the exact opinion copies needed for final review.

### 1:15-1:43 — Visible transformation

Show readiness counts and the PDF preview: linked TOC, categorized TOA, Roman front matter, body page 1,
and corrected heading hierarchy. Open the prepared DOCX beside the malformed source only if the switch is
fast and clean.

> The document is now professionally formatted and publication-checked. OpenCounsel—not Word—owns the
> semantic entries, final page labels, and audit trail.

### 1:43-2:08 — Honest source review

Open **Citations & sources** and show the four declared authority slots. Upload the prepared public
opinion PDFs.

> A citation or embedded hyperlink is not proof. OpenCounsel separately requests the source copies,
> binds each upload to a stable authority ID, and rejects undeclared or mismatched material.

### 2:08-2:30 — Verification and links

Run source verification. Show identity, exact-quotation status, remaining lawyer judgment, and eligible
embedded-link dispositions. Explicitly approve only durable-looking links.

> Exact quotation and source identity can pass deterministically. Whether the authority supports the
> characterization remains a lawyer's decision, and the report says so.

### 2:30-2:47 — Final package

Show the separate linked DOCX/PDF, final review ZIP, verification report, and abbreviated hashes.

> The result is the filing plus the evidence needed to review it: correction, publication, acquisition,
> source-verification, link, and hash manifests. The original and first-pass artifacts never change.

### 2:47-2:59 — National filing scale and close

Scroll once to the closing panel. Keep its methodology collapsed during narration.

> Nearly seventeen million civil cases enter American trial courts every year. If only five percent
> produce one qualifying package, this workflow represents roughly five hundred eighty-seven million
> dollars in annual professional capacity, even at a deliberately discounted two-hundred-dollar rate.

Stop. Do not add a terminal tour, architecture lecture, credits sequence, or speculative roadmap.

## Capture checklist

Capture three clean desktop images:

1. **Before/intake:** recording-grade hero, public matter identity, transformation card, stage rail, and
   primary demo action.
2. **After/publication:** result metrics plus linked TOC or TOA in the PDF preview.
3. **Source verification:** authority slots and final verification summary showing navigation, identity,
   exact quotation, and remaining lawyer review as distinct states.

Before recording:

- start from a clean Docker/runtime state with `docker compose up --build`;
- wait for `/healthz` before opening the browser;
- use a clean browser profile at 100% zoom with no personal tabs, bookmarks, notifications, or avatar;
- inspect every visible filename and download;
- run both passes once to warm LibreOffice, delete that job, then record a fresh job;
- verify first-pass hashes remain unchanged after finalization;
- confirm the national-scale panel fits one 16:9 viewport at 100% zoom and needs only one downward
  scroll from the completed workspace;
- delete the recorded job after capture and confirm its local artifacts are removed; and
- stop and remove the stack using the documented command.

## Final human-only submission steps

- [ ] Join/register for the challenge on Devpost.
- [x] Preserve the primary Codex `/feedback` session ID:
      `019f859f-7eba-7ef0-bdc9-406c796e0d8b`.
- [ ] Choose repository access: select and commit a real license before going public, or keep the
      repository private and add the required reviewer accounts.
- [ ] Record and upload the public sub-three-minute YouTube video.
- [ ] Add the three privacy-reviewed screenshots.
- [ ] Paste the submission copy and verify that no client or personal identifiers appear.
- [ ] Test the install instructions from a clean machine or clean Docker state.
- [ ] Submit before July 21, 2026 at 5:00 p.m. Pacific.
