---
name: opencounsel-brief-processor
description: Process an uploaded legal brief through OpenCounsel and return cleaned filing artifacts in chat. Use when the user uploads a DOCX brief and asks to fix or normalize formatting, generate or repair a table of contents or table of authorities, hyperlink cases, statutes, rules, or regulations, apply a court filing profile, render a PDF, or prepare a filing-ready review package. Coordinate uploaded files, OpenCounsel MCP tools, authority resolution, DOCX inspection, and PDF rendering; do not ask the user to run a CLI.
---

# OpenCounsel Brief Processor

Treat chat as the product interface. The user uploads files and states the desired result; never redirect them to a command line.

## Workflow

1. Identify the principal brief DOCX and any optional model brief, authorities, record package, or source-override manifest.
2. Infer the filing profile from the document and request. Ask one focused question only when jurisdiction or document type cannot be determined safely.
3. Stage the uploaded files in the confined OpenCounsel MCP input directory.
4. Call the coarse `clean_brief` MCP operation with the selected filing profile, optional confined
   ROA package, and exact citation-to-URL overrides. Do not split formatting, linking, and cite
   review into detached transforms.
5. Resolve unresolved canonical case citations using the minimum citation-only payload through an approved source connector. Never transmit surrounding client prose. Feed exact citation-to-URL resolutions back through a confined override manifest.
6. Run the FOSS publisher to compile explicit bookmark/`PAGEREF` TOC and TOA entries, calculate
   and deduplicate repeated-authority page labels, then render the published DOCX to PDF through
   the isolated LibreOffice adapter. Inspect both artifacts structurally; desktop Word remains a
   compatibility review surface, not a server dependency.
7. Verify:
   - reviewed `_Legal...` styles and filing-profile typography;
   - justified body and numbered headings;
   - native multilevel numbering;
   - TOC and categorized TOA presence and spacing;
   - page and section transitions;
   - links on every safely resolved case, statute, rule, and regulation occurrence;
   - corresponding linked authority entries in the generated TOA or an explicit abstention identifying why a TOA link could not be safely emitted;
   - no visible-text loss, metadata leakage, or mutation of the uploaded source.
8. Retry deterministic repair steps when validation fails. Surface only genuine ambiguities or unsupported structures.
9. Return directly in chat:
   - cleaned DOCX;
   - rendered PDF;
   - correction/formatting ledger;
   - citation and hyperlink report;
   - abstention report when nonempty.

## Safety Rules

- Never overwrite the uploaded file.
- Never put client text, filenames, metadata, or hashes into Git or CI.
- Do not modify signed packages or documents with unresolved tracked changes.
- Preserve existing valid links.
- Do not invent authority URLs. Use official, approved open, licensed override, or uniquely verified sources.
- Do not claim every authority is linked when unresolved or ambiguous citations remain.
- Never report an inserted native TOC/TOA field as a populated table. Use the explicit FOSS
  publication output for visible entries and calculated page references.

## Product Boundary

Internal CLI commands may support tests and development, but they are not the user interface. The complete user interaction is:

`upload in chat -> skill orchestration -> MCP processing -> validation/rendering -> downloadable DOCX/PDF in chat`.
