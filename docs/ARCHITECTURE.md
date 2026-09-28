# Architecture

## Current vertical slice

The implemented path is deliberately narrow:

```text
ROA ZIP -> deterministic validator -> source-document IR -> PostgreSQL -> exact locator resolver
              |                         |
              +-> immutable objects ----+
```

The canonical source model is `matter -> document -> representation -> page -> locator`. A locator
always names a page in a specific representation; physical PDF ordinals and printed record pages
are never silently conflated.

PostgreSQL is the canonical relational store. Binary inputs live in a content-addressed object
store. Full-text search can use PostgreSQL first; vector search remains optional and is not part of
this slice.

The second executable path audits briefs and can project reviewed authority links and native front
matter into a new file:

```text
DOCX + optional ROA -> safe OOXML reader -> occurrence ledger -> page-free front-matter source
                                           |                         |
                                           +-> link source           +-> TC/TA + TOC/TOA fields
                                                   |                          |
                              new DOCX + manifest <-+---- safe projectors ----+
```

It parses body paragraphs, footnotes, and endnotes, preserves existing external hyperlink targets,
resolves record cites locally, and extracts authority candidates. The supplied DOCX is never
edited. Hyperlink projection is hash-bound, writes a new artifact, and verifies visible text after
mutation.

The authority-source path extends the same provenance model:

```text
brief assertions -> acquisition manifest -> mapped source PDFs -> authority/page IR
                                                      |
                                   exact quote checks + ranked support pages
```

Existence, quotation fidelity, quotation-edit signals, and substantive characterization are
separate validation states. Deterministic passes may confirm identity and exact text. Substantive
support remains a review decision even when a model proposes the likely answer.

The local filing-preflight interface composes those paths without taking ownership of document
truth:

```text
DOCX + mapped/searchable ROA -> confined local job -> clean_brief -> FOSS publication
                                      |                    |
                               review/source reports   DOCX + PDF
                                      +--------- filing package --------+
```

Raw searchable PDFs become mapped packages only after an explicit consecutive-numbering
attestation. The UI stores inputs under generated job IDs, serves outputs through an artifact
allowlist, and can delete the complete job directory. It does not require PostgreSQL for this
single-filing path and does not add a network or model capability.

## Document-construction planes

| Plane | Canonical concern | Examples | May depend on |
|---|---|---|---|
| Source IR | Received authority/evidence and exact provenance | pages, blocks, R cites | object store, deterministic extractors |
| Work-product IR | Matter reasoning before final layout | facts, issues, arguments, authority refs | Source IR references |
| Word templates | Reusable blank office styles and structures | captions, headings, signature blocks | no matter content |
| Word projection | Human collaboration surface | DOCX, comments, tracked changes | Work-product IR + template |
| Filing-lock IR | Reviewed semantic document | accepted text, citations, footnotes | reconciled Word projection |
| Publication | Terminal rendering | LaTeX, PDF/A, filing PDF | Filing-lock IR only |

Word presentation resolves through four separately versioned inputs:

```text
case order / judge overlay -> court + document filing profile -> office style pack
                                                        -> blank template + manifest
```

The filing profile owns rule minima, required sections, length rules, and electronic-filing
requirements. The style pack owns choices permitted inside that envelope. The template owns
Word-specific realization—styles, numbering, sections, fields, and slots—but no matter content.
Unknown profile fields and incompatible style choices fail closed. See
[WORD_STYLES.md](WORD_STYLES.md).

Word is intentionally a projection, not the only canonical representation. The future round trip
is `WorkProductIR -> DOCX -> reviewed DOCX -> FilingIR -> LaTeX -> PDF`. Template selection,
semantic content, tracked-change reconciliation, and terminal typography therefore remain separate
modules and data contracts.

TOC and TOA logic follows the same separation. Heading and authority identity belong to semantic
records. Page numbers belong to a render manifest. Word fields and static publication tables are
projections of those records, not their source of truth.

## Models

Model use is optional and provider-neutral. A provider adapter receives a bounded request and
returns proposed data plus provenance. It cannot write canonical records directly. OpenAI may be
the first adapter, using the practitioner's own account, but no provider package is installed in
the current slice. No proprietary legal-practice platform is an architectural dependency.

## Reuse before invention

OpenCounsel should integrate mature components at their natural boundaries rather than clone a
general legal-AI application:

- borrow Mike's proven deployment shape—PostgreSQL, S3-compatible objects, pluggable providers,
  and LibreOffice where DOCX conversion is actually needed;
- evaluate LegalWork's document IR, OCR/redaction adapters, and skill packaging as source material,
  but do not copy its broad agent surface or noncommercial-licensed code without a license review;
- use docassemble when an interview-driven document assembly workflow fits; and
- use established libraries for OOXML, PDF, OCR, LaTeX, citations, and object storage rather than
  implement those formats.

The differentiating layer is the practice-specific canonical schema, exact provenance, validation
rules, and Word/filing round trip—not another chat shell.

## Total practice model

OpenCounsel is a set of bounded record systems joined by explicit, provenance-carrying transforms:

| System | Canonical records | Immediate use |
|---|---|---|
| Matter | opaque identity, participants, posture, objectives | prevents cross-matter leakage |
| Source | artifacts, representations, pages, locators | record and authority tie-out |
| Work product | facts, propositions, arguments, citations, revisions | drafting without format lock-in |
| Desk | messages, tasks, states, deadlines | restores Inbox -> work queue -> Processed Mail |
| Experience | court/judge/SOP cards and outcomes | captures procedure learned through practice |
| Doctrine | precedent atoms, doctrine lattice, retrieval schedule | rebuilds and retains legal command |
| Execution | model/tool runs, input hashes, proposals, validators, approvals | auditable optional automation |
| Publication | templates, Word projections, filing locks, render manifests | collaborative drafting and filing |

The unit of trust is not an answer; it is a reproducible transformation record. Every material
output should identify its source records, transform version, validation results, and human review
state. Probabilistic tools propose. Deterministic validators and the lawyer decide.

## Execution surfaces

The same core supports three deliberately different concerns:

| Surface | Responsibility | May not own |
|---|---|---|
| Python core | transforms, validators, schemas, immutable revisions | chat or transport state |
| CLI / MCP | typed invocation and artifact handoff | legal reasoning or document truth |
| Local web | confined intake, job status, review presentation, downloads | a second document pipeline |
| Skills | workflow sequencing, review gates, user-facing summaries | canonical records or silent edits |

The current MCP adapter has no network or model capability. It can create an immutable revision,
return metadata-only inspection results, and process one upload into a private corrected DOCX plus
correction ledger. Its first proof rule removes only unambiguous spaces before selected punctuation;
unsafe Word wrappers abstain and become review items. The next stage reuses the local citation
detector and deterministic official-source adapters to record every record cite and authority
occurrence without network access; it does not claim that a source was verified. A third pass
projects only allowlisted official/open candidates into a new DOCX, proves visible text unchanged,
and routes unsafe Word structures or signed packages to review. The final current pass compiles a
closed, page-free TOC/TOA source and, only when exactly one `[TOC]` or `[TOA]` slot exists, projects
native Word fields into a new artifact. Duplicate slots and unsafe packages abstain. Template work
can now follow without changing the coarse tool boundary. Skills can provide the
seamless “upload a brief, receive corrected DOCX plus correction ledger” experience by composing
hash-bound tools.
The local filing-preflight UI now supplies the interactive review table where record, authority,
source-copy, formatting, and audit status are materially easier to understand than a directory of
reports. See [WEB_INTERFACE.md](WEB_INTERFACE.md).

## Near-term sequence

The ordered implementation plan lives in [ROADMAP.md](ROADMAP.md). The first proof resolves an
exact printed record cite to its physical PDF ordinal against a generated synthetic package.
