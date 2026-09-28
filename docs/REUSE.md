# Reuse and license ledger

OpenCounsel imports packages at stable boundaries; it does not vendor or lightly rewrite upstream
applications. Architecture patterns are adopted where useful, while source code is copied only
under a compatible license with attribution and a specific maintenance reason.

## Adopted now

| Project | License | Boundary | Decision |
|---|---|---|---|
| SQLAlchemy / Alembic | MIT | relational persistence and migrations | dependency |
| psycopg | LGPL-3.0 | PostgreSQL driver | dependency, unmodified |
| pypdf | BSD-3-Clause | PDF structure/page count | dependency |
| python-docx | MIT | blank Word template inspection | dependency + thin adapter |
| eyecite | BSD-2-Clause | citation candidate extraction | dependency + thin adapter |
| lxml | BSD-3-Clause | bounded OOXML part reading | dependency + thin reader |

The attached TOA Agent v0.3.0a6 prototype was reviewed as MIT-licensed prior art. OpenCounsel now
adapts its proven native `TA`/`TOA` field mechanics: plain field-code runs rather than `w:vanish`,
italic case-name instruction spans, safe quote doubling, and optional long-case soft breaks. The
copyright and MIT terms are reproduced in [`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).
The prototype's bundled Word briefs, application shell, global-text resolver, and report layer were
not imported. OpenCounsel instead uses its existing paragraph-scoped occurrence ledger, closed
front-matter contract, hash-bound projector, synthetic fixtures, and exact-slot safety policy.

No upstream application is vendored. Dependencies and adapted components remain isolated at named
boundaries; adapters return proposals or metadata rather than writing canonical records.

## Approved for a later adapter

| Project | License | Useful capability | Gate before adoption |
|---|---|---|---|
| Docling | MIT | structured PDF/DOCX extraction and layout | pin a patched release; sandbox parsers; benchmark on legal files |
| Presidio | MIT | PII detection and reversible redaction workflows | add legal recognizers; measure false negatives; never equate PII with privilege |
| OpenAI Python | Apache-2.0 | the user's own model account | explicit egress policy, request ledger, retention controls, redaction option |
| docassemble | MIT project code | interview-driven document assembly | use as a bounded engine where interviews fit; do not rebuild it |
| LibreOffice | MPL/LGPL | DOCX/PDF conversion | invoke as isolated external process; verify output deterministically |
| Pandoc + Tectonic | GPL-2.0 / MIT | semantic-to-LaTeX/PDF publication | process boundary, pinned toolchain, render manifest |
| CourtListener APIs/data | project-specific terms | opinions, dockets, citation verification | cache primary-source provenance and respect API/data terms |
| docxtpl | LGPL-2.1 | Word-authored Jinja-style document projection | adopt only in projection module; keep semantic IR outside templates |

Docling versions 2.82.0 through 2.90.x had an unsafe Playwright HTML-rendering path; any adoption
must use 2.91.0 or later and keep remote fetch/JavaScript disabled for untrusted inputs.

## Study patterns, do not copy code

| Project | License | What to learn | Why code is not imported |
|---|---|---|---|
| Mike | AGPL-3.0 | Postgres + object store, provider adapters, matter workspace, LibreOffice boundary | do not copy code into the current all-rights-reserved repository absent a deliberate licensing decision |
| LegalWork | PolyForm Noncommercial 1.0.0 | document IR, OCR/redaction boundaries, local skill packaging | do not import code for law-practice use without a specific license analysis and permission |
| OLAW | MIT | simple tool-based legal retrieval and confirmation UX | useful reference, but no current need to import its application shell |

This ledger is an engineering screen, not a substitute for reviewing the exact version's license,
notices, transitive dependencies, and security advisories when an adapter is activated.
