# Build Week development provenance

Updated: 2026-07-21

This is an evidence map, not a claim that OpenCounsel emerged from one uninterrupted transcript.
The dated Git history and pull requests are the durable record.

## Chronology

OpenCounsel began during the Build Week contest period. Initial architecture and implementation were
developed with GPT-5.6 through ChatGPT Work. That work established the confidentiality boundary,
provider-neutral Python core, filing profiles, deterministic citation and source handling, FOSS
DOCX/PDF publication, local browser interface, public-filing demonstration, and Docker distribution.

This submitted Codex session then served as the principal contest-finalization and
release-engineering session. It performed substantive repository work rather than acting only as a
submission identifier:

- preserved the failed public job and reconstructed LibreOffice/pypdf page extraction;
- identified the exact `INTRODUCTION` zero-candidate TOC failure;
- committed the observable regression before the implementation fix;
- retained fail-closed handling for genuinely ambiguous body headings;
- repaired the clean rehearsal's four-slot selection and canonical source binding;
- ran the complete two-pass workflow from clean Docker state, explicitly approved its one eligible
  durable link, and verified linked outputs, immutability, deletion, and volume cleanup;
- ran focused, coverage, package, style, JavaScript, container, and real-LibreOffice checks;
- added and verified the bounded national filing-scale recording close; and
- reconciled judge-facing documentation and the restartable release handoff.

## Clean-context work

Bounded clean-context documentation work is represented by PR `#26` (privacy and product framing)
and PR `#27` (development provenance). This primary session inspected both branches and selectively
integrated only compatible documentation commits. It did not merge either branch wholesale or import
PR `#26`'s larger privacy-audit subsystem after the runtime was green.

No auxiliary session ID is stored in the repository, so none is invented here. If an auxiliary
session is included in Devpost, its returned ID must be added only after matching it to its actual PR
or commits.

## Evidence map

| Workstream | Session evidence | Commits or pull requests | Result |
|---|---|---|---|
| Initial architecture and implementation | GPT-5.6 through ChatGPT Work | Repository history through the pre-finalization `main` branch | Executable product and public demo foundation |
| Principal integration, diagnosis, and release | Primary submitted Codex session `019f859f-7eba-7ef0-bdc9-406c796e0d8b` | PR `#25`; `8a360a8` through `7f18fbe`, release documentation `0cce87c`, and final gate coverage `61014f5` | Fixed publication, hardened rehearsal, verified the explicit link-approval path and full gate, and prepared the contest release |
| Privacy and product framing | Bounded clean context; session ID not recorded | PR `#26`; selectively integrated as `a7d8844` and `23d305f` | Judge-facing README foundation |
| Provenance and roadmap cleanup | Bounded clean context; session ID not recorded | PR `#27`; selectively integrated as `4dadde2` and `2545eae` | Provenance record and concise contest cut line |

The primary `/feedback` session ID is preserved above for the Devpost submission. Do not imply that
the primary session authored every pre-existing line.

## Confidentiality boundary

Contest-facing sessions and demonstrations use only the public Dkt. 52 derivative, generated
fixtures, and prepared public authority files. Never expose client material, privileged work
product, publisher credentials, personal browser data, private matter identifiers, or generated
diagnostic artifacts.
