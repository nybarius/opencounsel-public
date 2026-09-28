# FOSS publication decision

Updated: 2026-07-18

## Decision

OpenCounsel owns the legal-document semantics and explicit front matter. LibreOffice is an isolated
FOSS layout engine, not the TOC/TOA compiler.

The terminal path is:

```text
reviewed semantic TOC/TOA
  -> explicit OOXML entries and categories
  -> bookmarks and internal/external hyperlinks
  -> standard PAGEREF first pass
  -> resolved static bookmark-backed TOC/TOA page labels
  -> isolated LibreOffice final PDF render
  -> hash-bound publication manifest
```

This removes the proprietary Aspose dependency and avoids relying on either Word or LibreOffice to
understand Word's opaque `TA`/`TOA` compilation behavior. Native `TC`/`TA`/`TOC`/`TOA` fields remain
available in the collaboration DOCX. The terminal publisher uses ordinary `PAGEREF` fields only as
an internal first-pass layout instrument. `published.docx` contains explicit visible entries with
static, deduplicated page labels and bookmark-backed links calculated from that layout pass. No
`PAGEREF` field remains in the delivered terminal DOCX.

## Publication contract

Input: a prepared DOCX plus the exact semantic `front-matter.json` and process manifest.

Output:

- `published.docx` with no `[TOC]` or `[TOA]` placeholders;
- `published.pdf` rendered by an isolated LibreOffice profile; and
- `publication.json` recording the engine/version, input and output hashes, page count, and
  semantic TOC/TOA counts.

The publisher fails closed when slots are missing or duplicated, semantic target text no longer
matches its recorded location, a required Word part is missing, an output already exists, the
renderer fails, or the PDF is empty, encrypted, or invalid.
It also fails when a heading page, authority-page sequence, or generated front-matter paragraph
cannot be identified unambiguously, or when any `PAGEREF` survives terminal compilation.

## Source-quality contract

Final targets are ordered by preference:

1. official court or legislative source;
2. canonical CourtListener opinion page;
3. explicit licensed or manual permalink;
4. otherwise no link and a review item.

Search pages, API endpoints, result lists, credential-bearing URLs, query strings on canonical
CourtListener opinions, and ambiguous targets are discovery artifacts and are never final links.

## Verified result

The synthetic end-to-end test exercises profile normalization, record cites resolved against a
generated ROA package, a canonical case override, an official statute link, full and short-form
authority occurrences, numbered and wrapped TOC entries, TOC/TOA compilation, bookmarks, first-pass
`PAGEREF` layout, static linked page labels, dotted leaders, and PDF rendering. A real LibreOffice
26.8 render produced separate Roman TOC/TOA pages and Arabic body pagination, deduplicated two
same-page authority occurrences to one linked page label, and left no placeholders or terminal
fields.

Desktop Word remains a compatibility review surface for the DOCX, but it is no longer a required
server dependency or the only component capable of producing visible front matter.
