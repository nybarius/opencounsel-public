# OpenCounsel development rules

## Product interface

- Chat and the local filing-preflight web app are product interfaces: upload brief and sources ->
  confined core/MCP tools -> reviewed DOCX/PDF and ledgers returned to the user.
- CLI commands are developer surfaces. Never require users to clone the repository, run commands, manage paths, or understand internal IDs.
- Ask only about genuine filing-profile, legal, source-identity, or structural ambiguity.

## Architecture and trust boundaries

- Keep legal-document logic in the provider-neutral Python core. MCP is typed transport; skills orchestrate tools and lawyer review.
- Keep templates, semantic work-product data, Word projections, filing-lock IR, and terminal publication as separate versioned contracts.
- Deterministic validators own file safety, hashes, exact citations, and publication invariants. Models may propose but never silently mutate canonical data.
- External resolution receives only normalized citation identity, never surrounding prose, filenames, matter identity, or document hashes.

## Confidentiality and immutability

- Never commit client material, client-derived text, identifying metadata, credentials, logs, hashes, snapshots, or private fixtures. Generate synthetic fixtures.
- Never overwrite uploads. Every transformation creates a hash-bound revision and separate lawyer-review report.
- Confine I/O to explicit roots; reject traversal, symlinks, unsafe or oversized containers, and undeclared network or model access.
- MCP outputs remain closed structured metadata unless a purpose-specific egress contract permits document prose.

## Word and publication

- Use generic `_Legal...` custom styles; desktop Word is the compatibility target for native numbering and fields.
- Numbered headings use native `I. / A. / 1. / a.` numbering. List definitions own number, tab, and hanging geometry; paragraphs contain no typed labels.
- TOC entries are single-spaced with 12 points after. Numbered levels advance in half-inch steps with proper hanging indents and tabs.
- The TOA starts on a new page. The main body begins in a new Word section so Roman front-matter and Arabic body pagination remain independent.
- Generate TOC/TOA semantics before pagination. Return an editable DOCX and update fields or publish an equivalent static final output.
- Link every uniquely resolved authority in text and expose the approved target from the rendered TOA; abstain visibly on ambiguity.

## Engineering discipline

- Begin behavior changes with a failing unit, contract, property, or regression test.
- Version persisted and cross-process schemas; reject unknown trust-boundary fields.
- Preserve public APIs absent a migration. Prefer mature standards and libraries over new parsers.
- Keep commits narrow and single-purpose. Before deleting a symbol, verify zero call sites.
- Avoid speculative abstractions and dependencies during refactor or cleanup.
- Do not create self-modifying workflows to work around connector failures; use direct repository writes or an authenticated local checkout.

## Continuity and checks

- On continuation, read `docs/PROJECT_STATE.md`, then inspect the active branch, PR, and relevant code.
- Replace `docs/PROJECT_STATE.md` after each tranche with a short factual handoff free of private data.
- Record durable decisions in Git; chat history is secondary.
- Do not infer that CI did not run from an empty or failing connector endpoint; distinguish push runs, PR runs, and connector visibility.
- Required gate:

```console
uv lock --check
uv run ruff check .
uv run mypy src
uv run pytest --cov=opencounsel --cov-report=term-missing
uv build
uv run python scripts/build_style_review.py --out /tmp/opencounsel-style-review
```
