# Local filing-preflight interface

OpenCounsel includes a private browser interface for the complete preparation and publication
path. It is a thin adapter over the same provider-neutral Python core used by the CLI and MCP
surfaces. It does not implement a second document pipeline.

## User workflow

1. Add a Word brief and either a mapped ROA ZIP or a searchable, consecutively numbered ROA PDF.
2. Select the court and document-type filing profile.
3. Confirm the page-numbering basis when the record is supplied as a raw PDF.
4. Run the local preparation job.
5. Review filing-readiness counts, source-copy requests, formatting rules, and immutable hashes.
6. Download the complete filing package or its individual DOCX, PDF, and review artifacts.

Raw-PDF intake is deliberately bounded. The user must attest that every PDF page has searchable
text and that record numbering is consecutive from the stated first page. A blank, encrypted,
oversized, non-searchable, or nonconsecutive record must instead be OCRed or supplied as a mapped
ROA package.

## Local trust boundary

- The server binds to `127.0.0.1` unless the operator explicitly selects another address.
- Uploaded names are display-only; files are stored under generated job IDs and fixed filenames.
- Uploads are capped at 100 MiB each and never overwrite an existing path.
- Job directories and outputs use private filesystem modes.
- Downloads resolve through an artifact allowlist; callers cannot request arbitrary paths.
- The result screen can delete the complete generated job directory after review.
- Responses disable caching and set a same-origin content-security policy.
- Uvicorn access logging is disabled so filenames and job routes do not enter a request log.
- The model and network policies remain disabled on the default preparation path.

## Run locally

```console
uv sync --all-groups
uv run opencounsel ui
```

Open `http://127.0.0.1:8765`. The interface includes a generated synthetic demonstration that
uses the real preparation, LibreOffice publication, reporting, and packaging path.

## Run with Docker

```console
docker compose up --build
```

The published port is restricted to the host loopback interface. The container runs as a
non-root user with dropped capabilities, a read-only root filesystem, a private named data
volume, and an isolated temporary filesystem for LibreOffice. PostgreSQL is not required for the
single-filing interactive path; the broader source-ingestion infrastructure retains its existing
PostgreSQL support.

## Delivered package

The ZIP includes:

- `published.docx` and `published.pdf`;
- `corrections.json`, `front-matter.json`, and `publication.json`;
- `process.json`, the immutable core manifest, and `symbolic-ai-conformance.json`, its pinned
  donor checks (also retained under `first-pass/` in the final review package);
- record-citation, heading, and authority audit tables;
- the mapped record PDF for local page navigation; and
- the authority source-copy request and intake ledgers.

The result screen also exposes the validated machine-readable ROA ZIP as a separate reusable
download. When intake begins with a raw searchable PDF, this is the package created by the live
converter; when intake begins with an existing mapped package, it is the validated input package.

The interface uses “source copy requested,” not “missing authority,” for an authority that was
detected and included in the TOA but still requires an opinion PDF or licensed export for
assertion-level source verification.

The home page introduces the demo, Review items, and Why did it decide that in three steps.
Every explanation has an expandable ledger receipt with its process and correction identifiers.
The Why tab provides downloads for the conformance checks and process receipt.

The symbolic-ai adapter reports field coverage for its pinned procedural-authority contract:
3 of 7 bindings and 6 of 11 predicates for a complete OpenCounsel process manifest. A supplied
review count records review work; it does not assert that a lawyer approved it. Predecessor and
context bindings, coverage closure, regression closure and locked-region evidence remain unsupplied.
The donor's negative laws are copied verbatim. No donor runtime, external call or model is loaded.
