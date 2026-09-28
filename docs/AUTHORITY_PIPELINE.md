# Authority acquisition and verification pipeline

This pipeline turns the authorities cited in a brief into a source-backed, page-addressable package.
It is separate from hyperlink projection, TOA generation, Word templates, and final publication.

```text
brief.docx
   -> authority occurrence graph
   -> acquisition bundle
   -> open-source resolution or publisher download list
   -> mapped authority PDFs
   -> provenance-preserving authority package
   -> deterministic verification report
```

## 1. Prepare an acquisition bundle

```console
uv run opencounsel prepare-authorities brief.docx --out authority-bundle
```

Optional CourtListener lookup transmits only normalized case identifiers:

```console
export COURTLISTENER_API_TOKEN='...'
uv run opencounsel prepare-authorities brief.docx \
  --courtlistener --verify-urls --out authority-bundle
```

The bundle contains:

| File | Purpose |
|---|---|
| `authority-manifest.json` | stable IDs, canonical cites, assertion contexts, source state, and verification targets |
| `missing-case-identifiers.txt` | v1-compatible filename containing detected cases whose reviewable source copies must be retrieved from Lexis/Westlaw or another provider |
| `authority-intake.csv` | mapping sheet for downloaded PDFs and source URLs |
| `source-evidence.json` | optional cached HTTP status, target, content type, and timestamp evidence |

The source-copy request line format is:

```text
canonical citation;case name;court;year;docket;authority ID
```

This file does **not** identify authorities missing from the brief or TOA. It lists detected case
authorities for which OpenCounsel lacks reviewable opinion text. A hyperlink is navigation, not
evidence that a quotation or characterization was verified. No surrounding brief prose enters the
source-copy request file. Assertion context remains in the private JSON manifest because it is
needed for quotation and characterization review.

## 2. Add downloaded PDFs

Put downloaded decisions in the bundle directory and fill `source_file` in `authority-intake.csv`.
The filenames need not match publisher filenames. The stable authority ID performs the join.

```csv
authority_id,canonical_citation,case_name,expected_filename,source_file,source_url
auth-abcd1234,2026 N.Y. Misc. LEXIS 1234,Smith v. Jones,auth-abcd1234.pdf,downloads/smith.pdf,
```

Authenticated Lexis or Westlaw retrieval stays outside OpenCounsel. The system consumes the PDF
the practitioner lawfully downloaded; it does not store credentials or scrape a publisher.

## 3. Build the machine-readable package

```console
uv run opencounsel package-authorities authority-bundle \
  --out matter-authorities.zip
```

The resulting ZIP contains:

- every mapped source PDF under its stable authority ID;
- SHA-256, original filename, page count, and source URL provenance;
- `pages.jsonl`, with page number, extracted text, and per-page text hash;
- the brief-side authority and assertion manifest; and
- an explicit list of detected authority IDs whose source copies are still absent from the
  verification package.

This is the authority analogue of the ROA machine-readable package. It preserves the received PDF
as a representation while making each page usable by deterministic checks and later model review.

## 4. Run the verification pass

```console
uv run opencounsel verify-authorities matter-authorities.zip \
  --out authority-verification.json
```

The report keeps four levels distinct:

| Level | Current executable result |
|---|---|
| Citation exists | passes only when a source is present and its text contains citation or case-name identity evidence; otherwise fails or requires review |
| Quotation exact | exact normalized-text comparison against the complete source package; missing sources block the check |
| Quotation signals complete | ordinary exact quotations inherit the exactness result; ellipses, brackets, and alteration/omission signals are surfaced for review |
| Characterization supported | never auto-passes; the report preserves each assertion and ranks likely pertinent pages for lawyer or bounded-model review |

The fourth level is intentionally more expensive. A later provider-neutral model pass may propose
support or contradiction using the ranked pages, headnotes, disposition, holding language, and
adjacent pincite text. It may not mark the assertion approved.

## Upload workflow in ChatGPT

The same stages work when ChatGPT is the execution surface:

1. Upload a `.docx` brief. Receive a linked copy, link manifest, authority acquisition manifest,
   missing-case list, and intake CSV.
2. Download missing sources from Lexis/Westlaw using the list, then upload the PDFs or publisher ZIP.
3. Receive a machine-readable authority ZIP plus a deterministic verification report.
4. For level-four review, request a characterization audit. Receive an assertion-by-assertion table
   with likely pages, quoted language, support assessment, and unresolved questions.

Real briefs, manifests, publisher PDFs, and verification reports remain matter files. None belongs
in Git, fixtures, telemetry, or public model prompts.
