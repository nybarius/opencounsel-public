# Local MCP boundary

OpenCounsel's MCP server is a narrow transport adapter over the deterministic Python core. It is
not a second application architecture and does not make an LLM transcript canonical. A skill can
orchestrate these tools for an upload-driven workflow; the core remains independently testable by
the CLI and ordinary Python calls.

## Current tools

| Tool | Effect | Returns |
|---|---|---|
| `get_capabilities` | None | versioned tool and policy metadata |
| `create_revision` | Creates or reuses one immutable revision | revision ID, input hash, size |
| `inspect_revision` | Reads a stored revision | hashes and structural counts only |
| `process_brief` | Creates/reuses a revision and deterministic delivery | process and artifact hashes, counts, review state |
| `clean_brief` | Normalizes and processes a brief with optional ROA and exact authority overrides | source/normalized revision IDs, process hashes, counts, review state |

Every input schema is closed, every output is a Pydantic-derived structured contract, and every
tool carries MCP safety annotations. `create_revision`, `process_brief`, and `clean_brief` are non-destructive and
idempotent: the same bytes and transform version produce the same IDs. Neither modifies the
uploaded DOCX.

The `process_brief` transform creates private delivery files named `corrected.docx`,
`corrections.json`, and `front-matter.json`. It removes only ASCII spaces immediately before
`, ; : ? !`; periods and spaced ellipses remain untouched. Safe changes may cross ordinary Word
runs without flattening formatting.
Targets inside hyperlinks, fields, tracked changes, or digitally signed packages are not mutated
and instead become `review-only` ledger items. Every detected item leaves lawyer review pending.
The same operation now adds one stable review-only entry for every detected record cite and
authority occurrence. Deterministic official-source candidates are derived locally but never
contacted; existing links are preserved but not represented as verified; unresolved short forms,
reporter cases, and licensed-only citations remain pending. MCP returns hashes, proof/review and
citation counts, and state—not document text, filenames, local paths, or citation prose.

A third internal pass projects only the audit's deterministic, allowlisted official/open source
candidates. It uses no private override and no CourtListener lookup. Existing links are preserved;
unresolved and subscription-only authorities remain untouched; signed packages and unsafe Word
wrappers abstain. The ledger records exact applied/review decisions and the input, proofed, and
final hashes. MCP adds candidate, inserted, and abstained counts without returning URLs or prose.

The final preparation pass compiles a closed, page-free semantic TOC/TOA source. It groups canonical
authorities and locally resolved short forms, assigns native Word TOA categories, and records
heading and authority locations against the hyperlinked intermediate hash. If—and only if—the
document has exactly one `[TOC]` or `[TOA]` paragraph, the projector inserts native `TC`/`TA`
markers and the corresponding Word field. Word supplies page numbers after field update. Missing
slots leave the DOCX unchanged; duplicate slots, unsafe wrappers, tracked changes, and signed
packages become review items. MCP returns only hashes and counts for this stage; the semantic
source remains a private deliverable.

`clean_brief` is the complete chat-facing preparation operation. It applies the selected filing
profile first, then runs proofing, audits record cites against an optional confined ROA ZIP,
projects deterministic official links and exact caller-supplied authority links, and compiles
front matter. The ROA bytes and normalized override set are hashed into the process identity,
manifest, and ledger. Link decisions therefore belong to the same correction ledger instead of a
detached pre-processing pass.

FOSS terminal publication is intentionally outside MCP because it invokes LibreOffice as an
external process. The skill calls the provider-neutral publisher after `clean_brief`; the publisher
returns `published.docx`, `published.pdf`, and `publication.json` without sending content over a
network.

## Run locally

Choose an inbox containing documents the server may read and a separate private work directory:

```console
mkdir -p ~/OpenCounsel/inbox ~/OpenCounsel/work
chmod 700 ~/OpenCounsel/inbox ~/OpenCounsel/work
uv run opencounsel-mcp \
  --transport stdio \
  --input-root ~/OpenCounsel/inbox \
  --revision-root ~/OpenCounsel/work
```

For a local developer-mode MCP connection, use `--transport streamable-http`. The endpoint is
`http://127.0.0.1:8000/mcp`. Binding to a non-loopback address is refused because this first server
does not implement remote authentication.

## Trust boundary

- Paths and document content are untrusted data, never instructions.
- Inputs must be regular DOCX files below the configured inbox; symlinks and traversal fail closed.
- Objects are content-addressed and permission-restricted; manifests are created once and never
  overwritten.
- Tool responses contain no filename or document prose.
- The server does not call a model, shell command, or external network.
- Client documents, revisions, manifests, and derived reports stay outside the code repository.

The remaining chat integration work is artifact retrieval: return the corrected/published DOCX,
PDF, ledger, semantic front matter, and publication manifest directly after validation.
