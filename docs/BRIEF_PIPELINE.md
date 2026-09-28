# Brief pipeline

The brief pipeline is a compiler with review gates. A DOCX supplied for audit is an input, not an
instruction to edit that document. Mutation belongs to a later, explicit projection operation that
writes a new artifact and preserves the input hash.

```text
reviewed sources -> WorkProductIR -> Word projection -> reviewed Word -> FilingIR -> PDF
                         |                |                  |              |
                  semantic content   blank template    reconciliation   pagination
```

## Current modules

| Module | Input | Output | Mutation |
|---|---|---|---|
| `briefs.docx` | DOCX | paragraphs, styles, footnotes, existing links, heading candidates | none |
| `briefs.proof` | inspected DOCX | deterministic proof candidates with stable IDs and offsets | none |
| `briefs.proof_docx` | DOCX + proof plan | corrected DOCX + applied/review decisions | new artifact only |
| `briefs.audit` | DOCX + optional ROA package | record-cite and authority occurrence ledger | none |
| `briefs.cite_check` | audited DOCX | stable, exact, network-disabled citation review findings | none |
| `briefs.front_matter` | reviewed brief audit | semantic TOC and canonical TOA source entries | none |
| `briefs.front_matter_docx` | linked DOCX + semantic front matter | native TC/TA markers and TOC/TOA fields | new artifact only |
| `briefs.clean` | DOCX + profile + optional ROA/authority overrides | one hash-bound preparation result | new artifacts only |
| `briefs.links` | brief audit + resolver results | allowlisted insertion plan and review queue | none |
| `briefs.hyperlink_stage` | proofed DOCX + local audit | final DOCX + exact applied/abstained link decisions | new artifact only |
| `briefs.sources` | authority ledger + optional local overrides | official, open, or licensed source candidates | optional citation-only egress |
| `briefs.link_docx` | DOCX + hash-bound plan | new DOCX + mutation manifest | new artifact only |
| `briefs.authority_manifest` | authority ledger + resolutions | acquisition list, intake map, assertion checks | none |
| `source.authority_package` | mapped authority PDFs | hashed source/page package | new artifact only |
| `source.authority_verify` | authority package | four-level verification report | none |
| `templates.registry` | blank DOCX/DOTX + TOML manifest | hash/style/role validation | none |
| `templates.profiles` | strict court/document TOML | active filing-rule envelope | none |
| `templates.build` | filing profile + office style pack | clean blank DOCX + v2 manifest | new artifact only |
| `templates.audit` | DOCX + filing profile | formatting-only private report | none |
| `work_product.projection` | revision and template identities | projection and filing-lock contracts | none |
| `publication.foss` | prepared DOCX + semantic front matter | static linked front matter DOCX + LibreOffice PDF + manifest | new artifacts only |

The attached or local matter document may be used to test read-only extraction. It is never a Git
fixture. Synthetic documents exercise the same code in tests.

`process_brief` audits citation locations against the immutable input revision before proof
projection, so every ledger offset is hash-bound to the same source surface. The coarse
`clean_brief` operation accepts an optional confined ROA package and records resolved and unresolved
record-cite counts against its hash.
Official URL patterns are derived locally but are not contacted; reporter cases, ambiguous short
forms, and subscription-only citations remain pending source review. Eligible official/open links
are then projected into a new DOCX. Each proof item is located against the immutable input hash;
each citation and hyperlink item is located against the proofed intermediate hash; the manifest
binds those hashes, the hyperlinked intermediate hash, the page-free front-matter source, and the
final corrected artifact. Native front-matter projection runs last and only at exact structural
slots.

## TOC module

TOC generation has three separate inputs:

1. semantic heading identity from WorkProductIR or reviewed DOCX reconciliation;
2. a template manifest that maps semantic roles to Word styles and TOC levels; and
3. a final page map produced by the selected pagination engine.

`FrontMatterSource.toc` deliberately has no page numbers. It does carry the native outline label
derived from reviewed heading styles so terminal projection can preserve `I. / A. / 1. / a.`
numbering without treating the typed label as heading text. When the linked DOCX contains exactly one
paragraph whose visible text is `[TOC]`, the Word projector emits reviewed `TC` markers at the
semantic headings and replaces the slot with a native `TOC` field. Word supplies page numbers when
the user updates collaboration fields. The FOSS publisher instead emits explicit visible entries
with bookmarks and ordinary `PAGEREF` fields for a first PDF layout pass. OpenCounsel resolves every
heading and authority page from that pass, deduplicates repeated-authority labels, writes static
bookmark-backed page links into the terminal DOCX, verifies that no `PAGEREF` remains, and renders
the final packet. Neither path treats pagination as heading identity.

## TOA module

`eyecite` supplies citation occurrences, not final authority identity. Full case citations become
canonical candidates. `Id.`, short cites, and unknown reporter fragments remain occurrences that
must be reconciled to a canonical authority before they can affect a TOA or receive a link.

The complete TOA path is:

```text
citation occurrences -> canonical authority registry -> reviewed category/name
                     -> Word-native field or explicit FOSS publication table
```

Statutes, rules, constitutional provisions, and secondary authorities should use separate
extractors behind the same occurrence contract. They should not be forced through a case-citation
parser.

The current compiler groups canonical full citations with locally resolved short forms, assigns
Word's seven TOA categories, and records every occurrence without pages. When the linked DOCX
contains exactly one `[TOA]` paragraph, the projector emits native `TA` markers and an all-category
`TOA` field. Case names are italicized in field instructions. Duplicate slots, unresolved
locations, unsafe wrappers, tracked changes, and signed packages abstain rather than guess.

## Decision-link module

Linking is an explicit five-stage operation:

1. extract reporter citations locally;
2. resolve only the normalized citation, not the surrounding work product;
3. accept exactly one verified result from an approved resolver;
4. produce an allowlisted insertion plan for lawyer review; and
5. apply the accepted plan to a new Word projection, then re-audit and render it.

Existing links are preserved. Ambiguous, unmatched, short-form, or non-allowlisted results go to a
review queue. The CourtListener adapter sends individual reporter citations rather than whole
paragraphs or documents. Deterministic official-source adapters cover U.S. Code, eCFR, New York
statutes, and New York slip opinions. Subscription-only sources enter through a private,
exact-citation override manifest; OpenCounsel does not scrape authenticated publishers.

## Word template separation

A registered template is blank and content-free. Its manifest binds semantic roles to Word style
names, declares structural slots, and pins the exact file hash. Matter content cannot be stored in
the registry.

```text
template registry:  blank DOCX/DOTX + manifest + hash + version
work product:       facts + propositions + sections + authorities + source support
projection:         work-product revision + template identity -> new DOCX
reconciliation:     reviewed DOCX -> accepted semantic changes
publication:        FilingIR + renderer -> final PDF + render manifest
```

`docxtpl` is a suitable candidate for Word-authored template projection when Jinja-style document
assembly is useful. `python-docx` remains appropriate for inspection and targeted OOXML work. The
semantic model must stay outside both libraries.

The first clean style pack and five filing profiles are executable. They synthesize blank templates
from explicit tokens rather than copying a matter document's OOXML. Semantic WorkProductIR
projection into those registered styles remains the next compiler stage.

## Security invariants

- no matter document or extracted text in Git, fixtures, telemetry, or CI;
- audit output directories use mode `0700` and files use mode `0600` where supported;
- no network call in DOCX inspection, record-cite audit, TOC source, or TOA source generation;
- external resolution receives the smallest useful citation payload under an explicit policy;
- every mutation writes a new artifact and records input, plan, transform, and output hashes; and
- model output may propose classifications or mappings but may not approve them.
