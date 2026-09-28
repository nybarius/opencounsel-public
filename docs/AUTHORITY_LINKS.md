# Authority hyperlinking

Authority hyperlinking is a separate compiler pass. It does not generate a TOA, alter a template,
or make Word the canonical work product.

```text
DOCX -> local occurrence ledger -> source candidates -> hash-bound link plan
     -> conservative OOXML projection -> visible-text verification -> new DOCX + manifest
```

## Command

The offline command links recognized U.S. Code, eCFR, New York statutes, and New York slip opinions
using deterministic official-source URL schemes. It leaves unresolved cases and ambiguous short
forms untouched and records them for review.

```console
uv run opencounsel link-brief draft.docx draft-linked.docx
```

CourtListener is opt-in because it transmits data. The adapter sends only normalized reporter
citations, never paragraphs, filenames, hashes, record citations, or surrounding brief text. Put
the API token in the environment rather than an argument:

```console
export COURTLISTENER_API_TOKEN='...'
uv run opencounsel link-brief draft.docx draft-linked.docx --courtlistener
```

The output manifest defaults to `draft-linked.links.json`. Both the DOCX and manifest are created
with mode `0600` where supported. Existing output files are never overwritten.

The coarse `process-brief` workflow runs a stricter offline subset automatically after proofing.
It inserts only deterministic URLs from the built-in official/open adapters, performs no
CourtListener lookup, consumes no private override, and records each applied or abstained candidate
against the proofed-document hash. The standalone command remains the explicit surface for private
overrides and opt-in citation-only resolution.

## Subscription-only and missing sources

A Lexis or Westlaw citation is an authority identity, not proof that an open copy exists. The
resolver follows this order:

1. preserve an existing hyperlink;
2. use a deterministic official court or code source;
3. use one unambiguous CourtListener result when the user enables that adapter;
4. use an exact local source override supplied by the practitioner; or
5. abstain and put the occurrence in the review queue.

Local overrides let a firm subscription permalink attach to the same citation without storing a
credential or teaching OpenCounsel to scrape an authenticated publisher:

```toml
schema_version = 1

[[authority]]
citation = "2026 N.Y. Misc. LEXIS 1234"
url = "https://plus.lexis.com/document/example"
note = "Firm subscription permalink"
```

```console
uv run opencounsel link-brief draft.docx draft-linked.docx \
  --overrides ~/.config/opencounsel/source-overrides.toml
```

The manifest is work-product-adjacent and may reveal research choices. Keep it with the matter, not
in Git.

## Recognition policy

`eyecite` recognizes cases and its supported law citations. A bounded parser adds multi-section
U.S. Code, CFR, and common New York statute forms. Detector results are reconciled by weighted
interval scheduling, so detector registration order cannot make a broad expression swallow a
better citation. Section-list parsing accepts only numbered section tokens and stops at clause
boundaries.

Full citations may become link candidates. `Id.`, `supra`, and short reporter forms do not become
new authorities. The authority graph resolves them only when a unique antecedent is provable. The
body is one ordered scope; every footnote and endnote is a separate scope. Ambiguous forms still
remain review items.

## Word mutation policy

The projector:

- requires the exact input hash named by the plan;
- writes a new DOCX through an atomic temporary file;
- preserves all untouched ZIP members and existing hyperlinks;
- refuses digitally signed packages and overlapping edits;
- skips citations that cross fields, tracked changes, existing hyperlinks, or complex wrappers;
- supports ordinary citations split across multiple Word runs; and
- reopens the result and proves that every inspected paragraph has identical visible text.

The direct OOXML backend is intentionally conservative. A later Windows Word backend can handle
field-heavy or tracked-change-heavy documents, but it must satisfy the same plan and verification
contracts.

## Next resolver work

- official New York decision lookup beyond deterministic slip-opinion URLs;
- official per-rule sources for NYCRR and court rules;
- richer docket/date identity extraction for vendor-only decisions;
- point-in-time source capture rather than current-law URLs alone; and
- Microsoft Word automation backend for structures the conservative OOXML writer rejects.
