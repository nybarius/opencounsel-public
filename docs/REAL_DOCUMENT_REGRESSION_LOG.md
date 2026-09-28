# Real-document regression log

Updated: 2026-07-18

This log records privacy-safe lessons from local acceptance runs. It must not contain matter names,
document text, client identifiers, source hashes, filenames, screenshots, or client-derived Git
fixtures. Each observed defect becomes a synthetic regression before the production code changes.

## Appellate brief and ROA acceptance tranche

### Terminal DOCX page-reference parity — fixed

- Symptom: the PDF showed calculated TOC/TOA pages, but the delivered DOCX retained unevaluated
  results and could display incorrect values when opened in Word.
- Cause: LibreOffice calculates `PAGEREF` values for PDF export but does not reliably persist them
  during DOCX save. Full LibreOffice save-through also rewrites unrelated Word styles and direct
  formatting.
- Program change: use `PAGEREF` only in an isolated first pass; resolve every heading and authority
  page from the rendered PDF; write static, bookmark-backed page labels into the original OOXML;
  fail if any terminal `PAGEREF` remains.
- Regression coverage: real LibreOffice test plus structural assertions that terminal front matter
  is static, complete, linked, deduplicated, and free of placeholders.

### Slip-op placeholder reporter typography — fixed

- Symptom: an underscore reporter placeholder preceding a slip-op citation was italicized with the
  case name.
- Cause: citation recovery absorbed the placeholder reporter into `case_name`, extending the TOA
  italic span.
- Program change: classify the placeholder as reporter text, preserve it in the display citation,
  and limit italics to the actual case name.
- Regression coverage: a synthetic slip-op citation proves the case-name boundary and final TOA
  run typography.

### Numbered and wrapped TOC entries — fixed

- Symptom: native point labels disappeared from terminal TOC entries and continuation lines began
  one-half inch beyond the first-line text.
- Causes: normalization correctly removed typed labels in favor of native Word numbering, but the
  semantic TOC did not retain the resulting label; separately, case-sensitive style lookup created
  duplicate `TOC1`/`TOC2`/`TOC3` style IDs when a source used lowercase built-in style names.
- Program changes: carry a page-free native number label in each TOC source entry; emit the label
  plus a real tab; reuse paragraph styles case-insensitively; preserve the intended half-inch
  hanging geometry so continuation text aligns with first-line text after the label.
- Regression coverage: native `I. / A. / 1. / a.` sequencing, long wrapped entries, case-insensitive
  style reuse, unique style IDs, and real rendered alignment.

### Authority presence versus source verification — clarified

- Observation: the acceptance packet contained every detected authority and its TOA entry, while
  the source-needs report could be read as saying that 30 authorities were missing.
- Cause: v1 acquisition terminology used “missing” and “source-needed” for detected authorities
  whose opinion text had not been supplied for quotation and characterization review.
- Program change: CLI metadata now reports detected-authority and source-copy-required counts
  separately; review notes and documentation state that navigation links do not prove substantive
  verification. The v1 machine field and filename remain readable for compatibility.
- Regression coverage: acquisition and CLI tests prove that a detected case can simultaneously be
  counted as present and as requiring a reviewable source copy.

### Canonical Standard of Review heading — fixed

- Symptom: the centered, all-caps `STANDARD OF REVIEW` paragraph was restyled as caption text and
  therefore disappeared from the compiled TOC.
- Cause: the semantic inspector recognized the source paragraph as a heading, but the formatting
  normalizer's canonical-section set omitted `STANDARD OF REVIEW`; its generic centered-paragraph
  fallback then applied the caption style before front-matter compilation.
- Program change: `STANDARD OF REVIEW` is a canonical major section and receives the same semantic
  legal heading style as the preliminary statement, summary, argument, and conclusion.
- Regression coverage: a deliberately misstyled centered paragraph must normalize to the major
  section style and survive semantic heading extraction. The regenerated real-document packet
  contains 16 TOC entries and links `STANDARD OF REVIEW` to body page 16.

## Standing acceptance checks

- DOCX and PDF front matter must show the same nonzero page labels.
- Terminal front matter must contain no placeholders, broken-reference text, or `PAGEREF` fields.
- TOC numbering and continuation alignment must survive normalization and publication.
- Only case names are italic in case entries; reporters, placeholders, pincites, courts, and years
  are roman.
- Profile typography remains effective after publication, including 14-point body and 12-point
  footnotes for the New York appellate profile.
- Every DOCX delivery is rendered to page images; front matter is reviewed at full resolution and
  unchanged body pages are verified by pixel comparison against the reviewed baseline.
- Authority-presence counts, navigation-link counts, and source-copy requirements remain separate;
  no report may describe a detected TOA authority as missing merely because verification content
  was not supplied.
- Canonical major sections, including `STANDARD OF REVIEW`, must survive style normalization and
  appear in the semantic TOC even when their incoming Word style is wrong.

## Tooling follow-up

- The synthetic style-review gate now runs headless LibreOffice with an isolated temporary user
  profile. This prevents a stale or concurrent default profile lock from producing exit code 77
  during repeatable local or CI review-packet generation.
