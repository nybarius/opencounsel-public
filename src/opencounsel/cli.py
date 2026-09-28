from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from opencounsel.briefs.audit import audit_brief
from opencounsel.briefs.authority_manifest import (
    build_authority_acquisition_manifest,
    write_authority_acquisition_manifest,
)
from opencounsel.briefs.clean import clean_brief as run_clean_brief
from opencounsel.briefs.docx import BriefDocxError
from opencounsel.briefs.link_docx import apply_authority_links, write_link_manifest
from opencounsel.briefs.links import plan_authority_links
from opencounsel.briefs.report import write_brief_audit
from opencounsel.briefs.source_evidence import verify_resolution_urls
from opencounsel.briefs.sources import load_source_overrides, resolve_authority_sources
from opencounsel.config import DEFAULT_CONFIG_PATH, ConfigError, init_config, load_settings
from opencounsel.objects import ContentAddressedStore
from opencounsel.publication.foss import publish_foss
from opencounsel.revisions import RevisionStore
from opencounsel.service import ConflictError, NotFoundError, import_roa, make_engine, resolve
from opencounsel.source.authority_package import (
    AuthorityPackageError,
    build_authority_package,
)
from opencounsel.source.authority_verify import verify_authority_package
from opencounsel.source.pdf_roa import package_searchable_pdf
from opencounsel.source.roa import RoaValidationError, inspect_roa_package
from opencounsel.templates.audit import audit_word_styles, write_style_audit
from opencounsel.templates.build import build_blank_word_template
from opencounsel.templates.profiles import (
    get_bundled_filing_profile,
    list_bundled_filing_profiles,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opencounsel")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="create privilege-first local configuration")

    inspect_parser = commands.add_parser(
        "inspect-roa", help="validate an ROA package without import"
    )
    inspect_parser.add_argument("package", type=Path)

    package_roa_parser = commands.add_parser(
        "package-roa",
        help="convert a searchable, consecutively numbered PDF into a validated ROA package",
    )
    package_roa_parser.add_argument("pdf", type=Path)
    package_roa_parser.add_argument("--out", type=Path, required=True)
    package_roa_parser.add_argument("--first-record-page", type=int, required=True)
    package_roa_parser.add_argument(
        "--numbering-verified",
        action="store_true",
        required=True,
        help="attest that PDF pages follow consecutive record numbering from the stated page",
    )

    brief_parser = commands.add_parser(
        "audit-brief", help="audit DOCX headings, record cites, and authority links locally"
    )
    brief_parser.add_argument("brief", type=Path)
    brief_parser.add_argument("--roa-package", type=Path)
    brief_parser.add_argument("--record-pdf", type=Path)
    brief_parser.add_argument("--out", type=Path, required=True)

    link_parser = commands.add_parser(
        "link-brief",
        help="write a new DOCX with verified authority hyperlinks and a private manifest",
    )
    link_parser.add_argument("brief", type=Path)
    link_parser.add_argument("output", type=Path)
    link_parser.add_argument("--overrides", type=Path)
    link_parser.add_argument(
        "--courtlistener",
        action="store_true",
        help="send only normalized case citations to CourtListener's citation lookup API",
    )
    link_parser.add_argument("--manifest", type=Path)
    link_parser.add_argument(
        "--verify-urls",
        action="store_true",
        help="check source URLs and fail closed on broken or unreachable targets",
    )
    link_parser.add_argument("--evidence-cache", type=Path)

    authority_parser = commands.add_parser(
        "prepare-authorities",
        help="emit a private authority acquisition and verification bundle from a DOCX",
    )
    authority_parser.add_argument("brief", type=Path)
    authority_parser.add_argument("--out", type=Path, required=True)
    authority_parser.add_argument("--overrides", type=Path)
    authority_parser.add_argument(
        "--courtlistener",
        action="store_true",
        help="send only normalized case identifiers to CourtListener",
    )
    authority_parser.add_argument("--verify-urls", action="store_true")
    authority_parser.add_argument("--evidence-cache", type=Path)

    package_authorities = commands.add_parser(
        "package-authorities",
        help="convert mapped authority PDFs into a provenance-preserving ZIP package",
    )
    package_authorities.add_argument("bundle", type=Path)
    package_authorities.add_argument("--out", type=Path, required=True)

    verify_authorities = commands.add_parser(
        "verify-authorities",
        help="run deterministic source, quotation, and review-target checks",
    )
    verify_authorities.add_argument("package", type=Path)
    verify_authorities.add_argument("--out", type=Path, required=True)

    process_parser = commands.add_parser(
        "process-brief",
        help=(
            "create an immutable brief revision, corrected DOCX, correction ledger, "
            "and semantic front matter"
        ),
    )
    process_parser.add_argument("brief", type=Path)
    process_parser.add_argument(
        "--work-root",
        type=Path,
        required=True,
        help="private directory for immutable revisions and delivery artifacts",
    )

    clean_parser = commands.add_parser(
        "clean-brief",
        help=(
            "normalize one brief and run ROA audit, authority linking, proofing, and "
            "TOC/TOA projection as one operation"
        ),
    )
    clean_parser.add_argument("brief", type=Path)
    clean_parser.add_argument("--profile", required=True)
    clean_parser.add_argument("--roa-package", type=Path)
    clean_parser.add_argument("--overrides", type=Path)
    clean_parser.add_argument(
        "--work-root",
        type=Path,
        required=True,
        help="private directory for immutable revisions and delivery artifacts",
    )

    publish_parser = commands.add_parser(
        "publish-foss",
        help="compile explicit PAGEREF TOC/TOA entries and render PDF with LibreOffice",
    )
    publish_parser.add_argument("process_id")
    publish_parser.add_argument("--work-root", type=Path, required=True)
    publish_parser.add_argument("--libreoffice", default="libreoffice")

    ui_parser = commands.add_parser(
        "ui", help="start the private local filing-preflight interface"
    )
    ui_parser.add_argument("--host", default="127.0.0.1")
    ui_parser.add_argument("--port", type=_port, default=8765)
    ui_parser.add_argument(
        "--work-root",
        type=Path,
        default=Path.home() / ".local" / "share" / "opencounsel" / "web",
    )
    ui_parser.add_argument("--libreoffice", default="libreoffice")

    commands.add_parser(
        "list-filing-profiles",
        help="list versioned court and document-type filing profiles",
    )

    template_parser = commands.add_parser(
        "build-template",
        help="build a clean blank DOCX and hash-bound manifest for a filing profile",
    )
    template_parser.add_argument("profile")
    template_parser.add_argument("output", type=Path)
    template_parser.add_argument("--manifest", type=Path)

    style_audit_parser = commands.add_parser(
        "audit-word-styles",
        help="emit a formatting-only DOCX audit without document prose",
    )
    style_audit_parser.add_argument("document", type=Path)
    style_audit_parser.add_argument("--profile", required=True)
    style_audit_parser.add_argument("--out", type=Path, required=True)

    import_parser = commands.add_parser("import-roa", help="validate and persist an ROA package")
    import_parser.add_argument("package", type=Path)
    import_parser.add_argument("--matter", required=True)
    import_parser.add_argument("--document", required=True)
    import_parser.add_argument("--expect", type=_record_range)

    resolve_parser = commands.add_parser("resolve", help="resolve an exact record cite")
    resolve_parser.add_argument("cite")
    resolve_parser.add_argument("--matter", required=True)
    resolve_parser.add_argument("--document", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "init":
            settings = init_config(args.config)
            _emit(
                {
                    "status": "ready",
                    "config": str(args.config),
                    "object_root": str(settings.object_root),
                    "model_policy": settings.model_policy,
                }
            )
            return 0
        if args.command == "inspect-roa":
            package = inspect_roa_package(args.package)
            _emit(
                {
                    "status": "valid",
                    "package_sha256": package.package.sha256,
                    "indexed_pdf_sha256": package.pdf.sha256,
                    "page_count": len(package.pages),
                    "record_page_range": [package.first_record_page, package.last_record_page],
                    "validations": [asdict(value) for value in package.validations],
                }
            )
            return 0
        if args.command == "package-roa":
            packaged = package_searchable_pdf(
                args.pdf,
                args.out,
                first_record_page=args.first_record_page,
                numbering_verified=args.numbering_verified,
            )
            package = inspect_roa_package(packaged.output)
            _emit(
                {
                    "status": "packaged",
                    "output": str(packaged.output),
                    "package_sha256": package.package.sha256,
                    "indexed_pdf_sha256": package.pdf.sha256,
                    "page_count": packaged.page_count,
                    "record_page_range": [
                        packaged.first_record_page,
                        packaged.last_record_page,
                    ],
                }
            )
            return 0
        if args.command == "audit-brief":
            audit = audit_brief(args.brief, args.roa_package)
            paths = write_brief_audit(
                audit,
                args.out,
                record_pdf_name=args.record_pdf.name if args.record_pdf else None,
            )
            _emit(
                {
                    "status": "audited",
                    "brief_sha256": audit.brief_sha256,
                    "heading_count": len(audit.headings),
                    "record_citation_count": len(audit.record_citations),
                    "unresolved_record_citation_count": audit.unresolved_record_citation_count,
                    "authority_count": len(audit.authorities),
                    "authority_candidate_count": audit.authority_candidate_count,
                    "unlinked_authority_candidate_count": audit.unlinked_authority_count,
                    "outputs": [str(path) for path in paths],
                }
            )
            return 0
        if args.command == "link-brief":
            audit = audit_brief(args.brief)
            overrides = load_source_overrides(args.overrides) if args.overrides else ()
            resolutions = resolve_authority_sources(
                audit,
                overrides=overrides,
                use_courtlistener=args.courtlistener,
            )
            if args.verify_urls:
                cache = args.evidence_cache or args.output.with_suffix(
                    ".source-evidence.json"
                )
                resolutions = verify_resolution_urls(resolutions, cache)
            plan = plan_authority_links(audit, resolutions)
            link_result = apply_authority_links(args.brief, args.output, plan)
            manifest = args.manifest or args.output.with_suffix(".links.json")
            write_link_manifest(manifest, plan, link_result)
            _emit(
                {
                    "status": "linked",
                    "input_sha256": link_result.input_sha256,
                    "output_sha256": link_result.output_sha256,
                    "inserted_count": link_result.inserted_count,
                    "review_count": len(link_result.review),
                    "output": str(args.output),
                    "manifest": str(manifest),
                }
            )
            return 0
        if args.command == "prepare-authorities":
            audit = audit_brief(args.brief)
            overrides = load_source_overrides(args.overrides) if args.overrides else ()
            resolutions = resolve_authority_sources(
                audit,
                overrides=overrides,
                use_courtlistener=args.courtlistener,
            )
            if args.verify_urls:
                cache = args.evidence_cache or args.out / "source-evidence.json"
                resolutions = verify_resolution_urls(resolutions, cache)
            manifest = build_authority_acquisition_manifest(audit, resolutions)
            acquisition_paths = write_authority_acquisition_manifest(manifest, args.out)
            _emit(
                {
                    "status": "prepared",
                    "brief_sha256": manifest.brief_sha256,
                    "detected_authority_count": len(manifest.authorities),
                    "authority_count": len(manifest.authorities),
                    "source_copy_required_count": manifest.source_copy_required_count,
                    "case_source_copy_required_count": (
                        manifest.case_source_copy_required_count
                    ),
                    # Retained for v1 CLI consumers. This means a source copy is required;
                    # it does not mean the cited authority was absent or unidentified.
                    "source_needed_count": manifest.source_copy_required_count,
                    "unresolved_occurrence_count": manifest.unresolved_occurrence_count,
                    "outputs": [str(path) for path in acquisition_paths],
                }
            )
            return 0
        if args.command == "package-authorities":
            package_result = build_authority_package(args.bundle, args.out)
            _emit({"status": "packaged", **asdict(package_result), "output": str(args.out)})
            return 0
        if args.command == "verify-authorities":
            summary = verify_authority_package(args.package, args.out)
            _emit({"status": "verified", **summary, "output": str(args.out)})
            return 0
        if args.command == "process-brief":
            revisions = RevisionStore(args.work_root, args.brief.parent)
            revision = revisions.create(args.brief)
            result = revisions.process(revision.revision_id)
            corrected, ledger = revisions.delivery_paths(result.process_id)
            front_matter = revisions.front_matter_path(result.process_id)
            _emit(
                {
                    **result.model_dump(mode="json"),
                    "corrected_document": str(corrected),
                    "correction_ledger": str(ledger),
                    "front_matter_source": str(front_matter),
                }
            )
            return 0
        if args.command == "clean-brief":
            revisions = RevisionStore(args.work_root, args.brief.parent)
            overrides = load_source_overrides(args.overrides) if args.overrides else ()
            cleaned = run_clean_brief(
                revisions,
                args.brief,
                args.profile,
                roa_package_path=args.roa_package,
                authority_overrides=overrides,
            )
            corrected, ledger = revisions.delivery_paths(cleaned.process.process_id)
            front_matter = revisions.front_matter_path(cleaned.process.process_id)
            _emit(
                {
                    **cleaned.model_dump(mode="json"),
                    "corrected_document": str(corrected),
                    "correction_ledger": str(ledger),
                    "front_matter_source": str(front_matter),
                }
            )
            return 0
        if args.command == "publish-foss":
            revisions = RevisionStore(args.work_root, args.work_root)
            publication = publish_foss(
                revisions,
                args.process_id,
                executable=args.libreoffice,
            )
            delivery = revisions.deliveries / args.process_id
            _emit(
                {
                    **publication.model_dump(mode="json"),
                    "published_document": str(delivery / "published.docx"),
                    "published_pdf": str(delivery / "published.pdf"),
                    "publication_manifest": str(delivery / "publication.json"),
                }
            )
            return 0
        if args.command == "list-filing-profiles":
            profiles = list_bundled_filing_profiles()
            _emit(
                {
                    "status": "ready",
                    "profiles": [
                        {
                            "profile_id": profile.profile_id,
                            "version": profile.version,
                            "jurisdiction": profile.jurisdiction,
                            "court": profile.court,
                            "document_type": profile.document_type,
                            "effective_from": profile.effective_from,
                            "effective_to": profile.effective_to,
                            "last_verified": profile.last_verified,
                        }
                        for profile in profiles
                    ],
                }
            )
            return 0
        if args.command == "build-template":
            manifest_path = args.manifest or args.output.with_suffix(".template.toml")
            template_result = build_blank_word_template(
                args.profile, args.output, manifest_path=manifest_path
            )
            _emit({"status": "built", **asdict(template_result)})
            return 0
        if args.command == "audit-word-styles":
            profile = get_bundled_filing_profile(args.profile)
            report = audit_word_styles(args.document, profile)
            write_style_audit(report, args.out)
            _emit(
                {
                    "status": "audited",
                    "document_sha256": report.document_sha256,
                    "profile_id": report.profile_id,
                    "finding_count": len(report.findings),
                    "error_count": sum(
                        finding.severity == "error" for finding in report.findings
                    ),
                    "output": str(args.out),
                }
            )
            return 0
        if args.command == "ui":
            from opencounsel.web.server import run

            run(
                host=args.host,
                port=args.port,
                root=args.work_root,
                libreoffice=args.libreoffice,
            )
            return 0

        settings = load_settings(args.config)
        engine = make_engine(settings.database_url)
        with Session(engine) as session:
            if args.command == "import-roa":
                import_result = import_roa(
                    session,
                    ContentAddressedStore(settings.object_root),
                    args.package,
                    matter_slug=args.matter,
                    document_key=args.document,
                    expected_range=args.expect,
                )
                _emit({"status": "imported", **asdict(import_result)})
            else:
                resolution = resolve(
                    session,
                    matter_slug=args.matter,
                    document_key=args.document,
                    cite=args.cite,
                )
                _emit(asdict(resolution))
        return 0
    except (
        BriefDocxError,
        AuthorityPackageError,
        ConfigError,
        ConflictError,
        NotFoundError,
        RoaValidationError,
        ValueError,
    ) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2
    except SQLAlchemyError:
        print(
            json.dumps({"status": "error", "error": "database operation failed"}),
            file=sys.stderr,
        )
        return 2
    except OSError:
        print(
            json.dumps({"status": "error", "error": "local I/O operation failed"}),
            file=sys.stderr,
        )
        return 2


def _record_range(value: str) -> tuple[int, int]:
    try:
        first, last = (int(part) for part in value.split(":", maxsplit=1))
    except (ValueError, TypeError) as exc:
        raise argparse.ArgumentTypeError("expected FIRST:LAST, e.g. 3:5") from exc
    if first < 1 or last < first:
        raise argparse.ArgumentTypeError("record-page range is invalid")
    return first, last


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65_535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def _emit(value: object) -> None:
    print(json.dumps(value, sort_keys=True, default=str))
