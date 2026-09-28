# Semantic TOC/TOA and Word fields

OpenCounsel treats front matter as a compiler problem, not as formatted prose to scrape repeatedly.
The `process-brief` workflow now emits a private `front-matter.json` artifact alongside
`corrected.docx` and `corrections.json`.

## Semantic source

`front-matter.json` is a closed, versioned contract bound to the exact post-hyperlink DOCX hash. It
contains:

- stable heading IDs, levels, text, native number labels, source styles, and Word paragraph
  locations;
- stable canonical-authority IDs, category assignments, display and short forms;
- exact full- and reconciled-short-citation occurrences in body text, footnotes, and endnotes;
- existing approved/open hyperlink targets; and
- a count of unresolved authority occurrences excluded from the TOA.

It deliberately contains no page numbers. Heading and authority identity survive a change in
renderer; pages belong to Word's field result or a later terminal render manifest.

The current native Word category mapping is:

| Category | Word slot |
|---|---:|
| Cases | 1 |
| Statutes | 2 |
| Other Authorities | 3 |
| Rules | 4 |
| Treatises | 5 |
| Regulations | 6 |
| Constitutional Provisions | 7 |

Case, federal/NY statute, federal rule, NYCRR, federal regulation, U.S./NY constitutional, common
Restatement, and Wright & Miller forms have separate bounded detectors behind the same occurrence
contract. `eyecite` supplies reporter occurrences; it does not own canonical TOA identity.

## Conservative Word projection

Word mutation requires an exact paragraph containing `[TOC]` or `[TOA]`:

- one `[TOC]` authorizes page-free `TC` markers for reviewed headings and a native `TOC` field;
- one `[TOA]` authorizes native `TA` markers for canonical authority occurrences and a native
  all-category `TOA` field; and
- no slot means semantic compilation only—OpenCounsel does not guess a location.

Two identical slots are ambiguous and therefore become review-only findings. Existing generated
fields are recognized and preserved, so reprocessing does not duplicate them. Field result text
initially remains `[TOC]` or `[TOA]`, which lets the projector prove that visible text is unchanged.
Open the result in Word and update fields before filing; Word then supplies the current pages.

Case names inside `TA` instructions use italic runs while reporters, slip-op reporter placeholders,
and parentheticals remain roman.
Embedded quotation marks are doubled according to Word field syntax. Long case entries may carry a
soft break after the case-name comma. Generated field runs are not marked `w:vanish`, because Word
may omit vanished `TA` fields when compiling a TOA.

## Safety and provenance

- The uploaded DOCX is never overwritten.
- Every semantic source and Word decision is hash-bound to the exact stage document.
- Signed packages remain byte-identical and produce review-only decisions.
- Targets inside tracked changes, existing fields, or unsupported Word wrappers abstain.
- Existing authority hyperlinks are preserved; a `TA` marker may follow an exact linked citation.
- Projection reopens the output and proves that visible text is unchanged.
- No network or model call occurs during compilation or projection.

## FOSS publication projection

`publication.foss` consumes the corrected collaboration DOCX and the same semantic source. It
replaces the two visible placeholders with explicit styled TOC and categorized TOA paragraphs,
adds bookmarks at every semantic target, links TOC text internally, reuses approved external
authority relationships, and emits standard `PAGEREF` fields for an internal first-pass PDF layout.
OpenCounsel reads every calculated TOC and TOA page label, collapses duplicate authority pages,
replaces all first-pass fields with static bookmark-backed links, verifies that no terminal
`PAGEREF` remains, and renders the final PDF. Native heading labels (`I. / A. / 1. / a.`) are carried
into the TOC with an explicit tab so wrapped text aligns under the first-line text. The section
break carried by the TOA slot is transferred to the last generated entry so Roman front matter and
Arabic body pagination remain separate. This path does not depend on Word's `TA`/`TOA` updater or a
proprietary document SDK.

The resulting `publication.json` binds the prepared input hash, published DOCX/PDF hashes, engine
version, page count, and semantic entry counts. Reviewed-Word reconciliation and filing-lock IR
remain later gates.
