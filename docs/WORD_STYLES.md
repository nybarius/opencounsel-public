# Filing profiles and clean Word styles

OpenCounsel separates court rules, document-family structure, office style, and matter content. A
reusable template may encode presentation and document mechanics, but it must not contain client
text or silently override a filing requirement.

## Resolution model

```text
case-specific order / judge overlay
              ↓
court + jurisdiction + document-type profile
              ↓
office style pack
              ↓
blank DOCX + versioned manifest
              ↓
matter content projected into a new DOCX
```

Conflicts fail closed. A department, circuit, district, or judge overlay refines a base profile; it
does not fork the Word implementation or embed matter text in a template.

## Styles-first invariant

Recurring typography, alignment, indentation, spacing, keep behavior, widow control, outline
levels, tab stops, and list bindings belong in Word styles or list definitions. Manual tabs,
repeated spaces, blank spacer paragraphs, typed heading numbers, and forced heading line breaks are
not body-layout controls.

## Current office style pack

The `opencounsel-clean-serif` style pack, version `2026.8`, uses Times New Roman and justified body
text within each filing profile's rule envelope. Custom styles are generic and begin with `_Legal`;
they are not branded to OpenCounsel.

| Semantic role | Word style | Construction rule |
|---|---|---|
| Body | `_LegalBody` | Justified, double-spaced, 0.5-inch first-line indent |
| Body without indent | `_LegalBodyNoIndent` | Same rule envelope without first-line indent |
| Block quote | `_LegalBlockQuote` | Justified, single-spaced where allowed, indented both sides |
| Footnote | `_LegalFootnote` | Justified, single-spaced, profile-controlled minimum size |
| Document title | `_LegalDocumentTitle` | Centered, bold, excluded from the TOC outline |
| Major section | `_LegalHeadingBoldCtrUnderline` | Centered, bold, underlined, TOC level 1 |
| Argument outline | `_LegalOutline` | Named Word numbering style for the complete hierarchy |
| Point | `_LegalHeadingNum1` | `I.`, justified, TOC level 2 |
| Subpoint | `_LegalHeadingNum2` | `A.`, justified, TOC level 3 |
| Sub-subpoint | `_LegalHeadingNum3` | `1.`, justified, TOC level 4 |
| Paragraph heading | `_LegalHeadingNum4` | `a.`, justified, TOC level 5 |
| TOC title | `_LegalTOCTitle` | Centered, bold, underlined |
| TOA title | `_LegalTOATitle` | Centered, bold, underlined, page break before |
| TOA category | `_LegalTOACategory` | Flush left, title-case source text rendered in small caps |
| TOA entry | `Table of Authorities` | Single-spaced, 0.5-inch hanging indent |
| Signature | `_LegalSignature` / `_LegalSignatureLast` | Single-spaced block kept together |
| Hyperlink | `Hyperlink` | Black and underlined |

## Heading hierarchy and geometry

Principal argument points are all caps. Subordinate headings are title case. The numbered argument
hierarchy is the same across the presently supported appellate and motion families:

| Body level | Number | Number position | Text and wrapped-line position | TOC level |
|---:|---|---:|---:|---:|
| 1 | `I.` | 0.0 in | 0.5 in | 2 |
| 2 | `A.` | 0.5 in | 1.0 in | 3 |
| 3 | `1.` | 1.0 in | 1.5 in | 4 |
| 4 | `a.` | 1.5 in | 2.0 in | 5 |

The hierarchy is one named Word multilevel list. The list definition owns number position, tab
suffix, text position, hanging indent, restart behavior, and level linkage. Heading styles own
typography, justification, paragraph spacing, outline level, and keep behavior. A heading and its
automatic number remain one semantic paragraph.

Desktop Microsoft Word is the compatibility target. Word Mobile is known to render automatic list
tabs differently. LibreOffice/PDF rendering validates publication layout but does not establish
client-specific Word behavior.

## Table of contents

- Every entry is single-spaced within the entry and has 12 points after it.
- Contextual spacing is explicitly disabled, so Word cannot collapse the 12-point gap between
  consecutive entries that use the same TOC style.
- TOC level 1 is flush left.
- Each numbered level advances the number and text by 0.5 inch.
- Each numbered level uses a 0.5-inch hanging indent and a real tab from the number to the text.
- The page number is right aligned with a dot leader.

## Table of authorities and sections

The TOA title has page-break-before, so the TOA begins on a new page after the TOC. Category source
text is title case and rendered in small caps. The preliminary statement begins after a new-page
section break. Front matter uses lowercase Roman numbering; merits text starts Arabic numbering at
1 with the first displayed page number suppressed when required by the profile.

## Review gate

```console
uv run opencounsel list-filing-profiles
uv run opencounsel build-template ny-ad-appellant-brief blank.docx
uv run opencounsel audit-word-styles draft.docx \
  --profile ny-ad-appellant-brief --out style-audit.json
uv run python scripts/build_style_review.py --out /private/new-review-directory
```

A template is not filing-ready merely because tests pass. Open populated samples in desktop Word,
update fields, and inspect them page by page. PDF previews are emitted when LibreOffice is available
and should also be inspected. Matter content remains outside Git.
