from __future__ import annotations

import csv
import hashlib
import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from opencounsel.briefs.ir import AuthorityOccurrence, BriefAudit
from opencounsel.briefs.links import AuthorityResolution

SOURCE_STATUS_AVAILABLE = "available"
SOURCE_STATUS_COPY_REQUIRED = "source-needed"


@dataclass(frozen=True, slots=True)
class AuthorityAssertion:
    part: str
    paragraph_index: int
    citation_text: str
    citation_type: str
    context: str
    resolution_basis: str | None


@dataclass(frozen=True, slots=True)
class AuthorityNeed:
    authority_id: str
    canonical_citation: str
    case_name: str | None
    category: str
    court: str | None
    year: str | None
    docket: str | None
    source_status: str
    source_url: str | None
    source_resolver: str | None
    expected_filename: str
    assertions: tuple[AuthorityAssertion, ...]
    verification_targets: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class AuthorityAcquisitionManifest:
    brief_sha256: str
    authorities: tuple[AuthorityNeed, ...]
    unresolved_occurrence_count: int

    @property
    def source_copy_required_count(self) -> int:
        """Count detected authorities that still need reviewable source content."""
        return sum(requires_source_copy(item) for item in self.authorities)

    @property
    def case_source_copy_required_count(self) -> int:
        """Count detected case authorities that still need a source copy."""
        return sum(
            item.category == "cases" and requires_source_copy(item)
            for item in self.authorities
        )


def build_authority_acquisition_manifest(
    audit: BriefAudit,
    resolutions: tuple[AuthorityResolution, ...] = (),
) -> AuthorityAcquisitionManifest:
    verified: dict[str, list[AuthorityResolution]] = {}
    for resolution in resolutions:
        if resolution.status == "verified" and resolution.url:
            verified.setdefault(resolution.normalized_citation.casefold(), []).append(resolution)

    grouped: dict[str, list[AuthorityOccurrence]] = {}
    unresolved = 0
    for authority in audit.authorities:
        canonical = authority.resolved_citation
        if canonical is None and authority.is_canonical_candidate:
            canonical = authority.normalized_text
        if canonical is None:
            unresolved += 1
            continue
        grouped.setdefault(canonical, []).append(authority)

    needs: list[AuthorityNeed] = []
    for canonical, occurrences in grouped.items():
        exemplar = next(
            (item for item in occurrences if item.is_canonical_candidate), occurrences[0]
        )
        groups = dict(exemplar.groups)
        matches = verified.get(canonical.casefold(), [])
        selected = matches[0] if len(matches) == 1 else None
        authority_id = _authority_id(exemplar.category, canonical)
        needs.append(
            AuthorityNeed(
                authority_id=authority_id,
                canonical_citation=canonical,
                case_name=exemplar.case_name,
                category=exemplar.category,
                court=groups.get("court"),
                year=groups.get("year"),
                docket=groups.get("docket"),
                source_status=(
                    SOURCE_STATUS_AVAILABLE if selected else SOURCE_STATUS_COPY_REQUIRED
                ),
                source_url=selected.url if selected else None,
                source_resolver=selected.resolver if selected else None,
                expected_filename=f"{authority_id}.pdf",
                assertions=tuple(
                    AuthorityAssertion(
                        part=item.part,
                        paragraph_index=item.paragraph_index,
                        citation_text=item.text,
                        citation_type=item.citation_type,
                        context=item.context,
                        resolution_basis=item.resolution_basis,
                    )
                    for item in occurrences
                ),
                verification_targets=(
                    "citation-exists",
                    "quotation-exact",
                    "quotation-signals-complete",
                    "characterization-supported",
                ),
            )
        )
    needs.sort(key=lambda item: (item.category, item.canonical_citation.casefold()))
    return AuthorityAcquisitionManifest(audit.brief_sha256, tuple(needs), unresolved)


def write_authority_acquisition_manifest(
    manifest: AuthorityAcquisitionManifest,
    output_dir: Path,
) -> tuple[Path, ...]:
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_dir.chmod(0o700)
    json_path = output_dir / "authority-manifest.json"
    # Keep the v1 filename for compatibility. Its contents identify detected cases whose
    # source copies are still required; it is not a list of authorities absent from the brief.
    source_request_path = output_dir / "missing-case-identifiers.txt"
    intake_path = output_dir / "authority-intake.csv"
    _write_private_json(
        json_path,
        {
            "schema_version": 1,
            "brief_sha256": manifest.brief_sha256,
            "unresolved_occurrence_count": manifest.unresolved_occurrence_count,
            "authorities": [asdict(item) for item in manifest.authorities],
        },
    )
    missing_lines = [
        _semicolon_identifier(item)
        for item in manifest.authorities
        if item.category == "cases" and requires_source_copy(item)
    ]
    _write_private_text(
        source_request_path,
        "\n".join(missing_lines) + ("\n" if missing_lines else ""),
    )
    fd = os.open(intake_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=(
                "authority_id",
                "canonical_citation",
                "case_name",
                "expected_filename",
                "source_file",
                "source_url",
            ),
        )
        writer.writeheader()
        for item in manifest.authorities:
            writer.writerow(
                {
                    "authority_id": item.authority_id,
                    "canonical_citation": item.canonical_citation,
                    "case_name": item.case_name or "",
                    "expected_filename": item.expected_filename,
                    "source_file": "",
                    "source_url": item.source_url or "",
                }
            )
    return json_path, source_request_path, intake_path


def requires_source_copy(item: AuthorityNeed) -> bool:
    """Return whether substantive verification lacks reviewable source content."""
    return item.source_status == SOURCE_STATUS_COPY_REQUIRED


def _semicolon_identifier(item: AuthorityNeed) -> str:
    return ";".join(
        _clean_field(value)
        for value in (
            item.canonical_citation,
            item.case_name,
            item.court,
            item.year,
            item.docket,
            item.authority_id,
        )
    )


def _clean_field(value: str | None) -> str:
    return re.sub(r"[;\r\n]+", " ", value or "").strip()


def _authority_id(category: str, citation: str) -> str:
    digest = hashlib.sha256(f"{category}\0{citation.casefold()}".encode()).hexdigest()[:16]
    return f"auth-{digest}"


def _write_private_json(path: Path, payload: object) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")


def _write_private_text(path: Path, text: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(text)
