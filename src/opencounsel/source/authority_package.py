from __future__ import annotations

import csv
import hashlib
import json
import os
import tempfile
import zipfile
from collections.abc import Mapping, Set
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

from pypdf import PdfReader
from pypdf.errors import PdfReadError

MAX_SOURCE_BYTES = 100 * 1024 * 1024


class AuthorityPackageError(ValueError):
    """Raised when an authority acquisition bundle cannot be packaged safely."""


@dataclass(frozen=True, slots=True)
class AuthoritySourceRecord:
    authority_id: str
    canonical_citation: str
    case_name: str | None
    original_filename: str
    package_member: str
    sha256: str
    page_count: int
    source_url: str | None


@dataclass(frozen=True, slots=True)
class AuthorityPackageResult:
    package_sha256: str
    source_count: int
    page_count: int
    missing_authority_ids: tuple[str, ...]


def extract_pdf_link_annotations(
    source: Path,
    *,
    authority_id: str,
) -> dict[str, object]:
    """Extract external PDF links without treating navigation as verified authority text."""
    if (
        not source.is_file()
        or source.is_symlink()
        or source.suffix.lower() != ".pdf"
        or source.stat().st_size == 0
        or source.stat().st_size > MAX_SOURCE_BYTES
    ):
        raise AuthorityPackageError("authority source is not a readable PDF")
    data = source.read_bytes()
    source_sha256 = hashlib.sha256(data).hexdigest()
    try:
        reader = PdfReader(source, strict=True)
        if reader.is_encrypted:
            raise AuthorityPackageError("encrypted authority PDFs are not accepted")
        pages = tuple(reader.pages)
    except AuthorityPackageError:
        raise
    except (OSError, PdfReadError, ValueError) as exc:
        raise AuthorityPackageError("authority source is not a readable PDF") from exc

    links: list[dict[str, object]] = []
    malformed_annotation_count = 0
    for page_number, page in enumerate(pages, start=1):
        annotations = page.get("/Annots", ())
        if not isinstance(annotations, (list, tuple)):
            malformed_annotation_count += 1
            continue
        for annotation_index, reference in enumerate(annotations):
            try:
                annotation = reference.get_object()
                if not isinstance(annotation, Mapping):
                    malformed_annotation_count += 1
                    continue
                if str(annotation.get("/Subtype", "")) != "/Link":
                    continue
                action = annotation.get("/A")
                coordinates = _rectangle_coordinates(annotation.get("/Rect"))
                if not isinstance(action, Mapping) or coordinates is None:
                    malformed_annotation_count += 1
                    continue
                target = action.get("/URI")
                if not isinstance(target, str) or not target.strip():
                    malformed_annotation_count += 1
                    continue
                original_url = target.strip()
                classification, normalized_url, abstention_reason = _classify_link_url(
                    original_url
                )
                link_id = _link_id(
                    authority_id,
                    source_sha256,
                    page_number,
                    annotation_index,
                    coordinates,
                    original_url,
                )
                eligible = classification == "durable-candidate"
                links.append(
                    {
                        "link_id": link_id,
                        "authority_id": authority_id,
                        "source_pdf_sha256": source_sha256,
                        "page_number": page_number,
                        "annotation_rectangle": coordinates,
                        "original_target_url": original_url,
                        "normalized_candidate_url": normalized_url,
                        "classification": classification,
                        "approval_status": "pending" if eligible else "rejected",
                        "final_inserted_url": None,
                        "abstention_reason": (
                            "Explicit lawyer approval is required."
                            if eligible
                            else abstention_reason
                        ),
                    }
                )
            except (AttributeError, KeyError, TypeError, ValueError):
                malformed_annotation_count += 1
    return {
        "schema_version": 1,
        "authority_id": authority_id,
        "source_pdf_sha256": source_sha256,
        "malformed_annotation_count": malformed_annotation_count,
        "links": links,
    }


def dispose_pdf_link_annotations(
    extraction: Mapping[str, object],
    *,
    approved_link_ids: Set[str],
    source_identity_verified: bool,
) -> dict[str, object]:
    raw_links = extraction.get("links")
    if extraction.get("schema_version") != 1 or not isinstance(raw_links, list):
        raise AuthorityPackageError("PDF link extraction has an unsupported schema")
    known_ids = {
        item.get("link_id")
        for item in raw_links
        if isinstance(item, Mapping) and isinstance(item.get("link_id"), str)
    }
    if not set(approved_link_ids) <= known_ids:
        raise AuthorityPackageError("link approval references an undeclared candidate")

    disposed: list[dict[str, object]] = []
    for raw in raw_links:
        if not isinstance(raw, Mapping):
            raise AuthorityPackageError("PDF link extraction has an unsupported schema")
        link = dict(raw)
        link_id = link.get("link_id")
        classification = link.get("classification")
        candidate = link.get("normalized_candidate_url")
        if not source_identity_verified:
            link.update(
                {
                    "approval_status": "rejected",
                    "final_inserted_url": None,
                    "abstention_reason": (
                        "Source identity was not verified; link approval is blocked."
                    ),
                }
            )
        elif (
            classification == "durable-candidate"
            and isinstance(link_id, str)
            and link_id in approved_link_ids
            and isinstance(candidate, str)
        ):
            link.update(
                {
                    "approval_status": "approved",
                    "final_inserted_url": candidate,
                    "abstention_reason": None,
                }
            )
        elif classification == "durable-candidate":
            link.update(
                {
                    "approval_status": "pending",
                    "final_inserted_url": None,
                    "abstention_reason": "Explicit lawyer approval is required.",
                }
            )
        else:
            link.update(
                {
                    "approval_status": "rejected",
                    "final_inserted_url": None,
                }
            )
        disposed.append(link)

    return {
        "schema_version": 1,
        "authority_id": extraction.get("authority_id"),
        "source_pdf_sha256": extraction.get("source_pdf_sha256"),
        "source_identity_verified": source_identity_verified,
        "malformed_annotation_count": extraction.get("malformed_annotation_count", 0),
        "approved_link_count": sum(
            link.get("approval_status") == "approved" for link in disposed
        ),
        "links": disposed,
    }


def write_pdf_link_disposition_manifest(
    disposition: Mapping[str, object],
    output: Path,
) -> Path:
    if disposition.get("schema_version") != 1 or not isinstance(
        disposition.get("links"), list
    ):
        raise AuthorityPackageError("PDF link disposition has an unsupported schema")
    if output.exists() or output.is_symlink():
        raise AuthorityPackageError("PDF link disposition manifest already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(disposition, stream, indent=2, sort_keys=True)
            stream.write("\n")
        output.chmod(0o600)
    except Exception:
        output.unlink(missing_ok=True)
        raise
    return output


def _rectangle_coordinates(value: object) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        return [float(item) for item in value]
    except (TypeError, ValueError):
        return None


def _classify_link_url(url: str) -> tuple[str, str | None, str | None]:
    if any(ord(character) < 32 for character in url):
        return "invalid-target", None, "The annotation target contains control characters."
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "invalid-target", None, "The annotation target is not a valid URL."
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return "invalid-target", None, "Only absolute HTTP(S) document links are eligible."
    lower_path = parsed.path.casefold()
    risky_path_tokens = ("/search", "/session", "/login", "/auth", "/request", "/track")
    if parsed.query or parsed.fragment or any(token in lower_path for token in risky_path_tokens):
        return (
            "ephemeral-or-tracking",
            None,
            "The URL contains search, session, request, fragment, or tracking state.",
        )
    if lower_path.endswith(".pdf"):
        return "durable-candidate", url, None
    return (
        "durability-unproven",
        None,
        "The URL is not sufficiently document-specific to establish durability.",
    )


def _link_id(
    authority_id: str,
    source_sha256: str,
    page_number: int,
    annotation_index: int,
    rectangle: list[float],
    original_url: str,
) -> str:
    material = json.dumps(
        [
            authority_id,
            source_sha256,
            page_number,
            annotation_index,
            rectangle,
            original_url,
        ],
        separators=(",", ":"),
    )
    return f"link-{hashlib.sha256(material.encode()).hexdigest()[:20]}"


def build_authority_package(bundle_dir: Path, output: Path) -> AuthorityPackageResult:
    if not bundle_dir.is_dir() or bundle_dir.is_symlink():
        raise AuthorityPackageError("authority bundle must be a regular directory")
    manifest_path = bundle_dir / "authority-manifest.json"
    intake_path = bundle_dir / "authority-intake.csv"
    manifest = _load_manifest(manifest_path)
    intake = _load_intake(intake_path)
    manifest_authorities = manifest["authorities"]
    if not isinstance(manifest_authorities, list):
        raise AuthorityPackageError("authority manifest has an unsupported schema")
    authorities = {
        item["authority_id"]: item
        for item in manifest_authorities
        if isinstance(item, dict) and isinstance(item.get("authority_id"), str)
    }
    if not authorities:
        raise AuthorityPackageError("authority manifest contains no authorities")
    unknown = sorted(set(intake) - set(authorities))
    if unknown:
        raise AuthorityPackageError("authority intake references an unknown authority ID")
    if output.exists():
        raise AuthorityPackageError("authority package output already exists")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    sources: list[AuthoritySourceRecord] = []
    page_rows: list[dict[str, object]] = []
    source_bytes: dict[str, bytes] = {}
    for authority_id, row in intake.items():
        source_file = row.get("source_file", "").strip()
        if not source_file:
            continue
        path = _confined_source(bundle_dir, source_file)
        data = path.read_bytes()
        if len(data) > MAX_SOURCE_BYTES:
            raise AuthorityPackageError("authority PDF exceeds 100 MiB")
        try:
            reader = PdfReader(path, strict=True)
            pages = tuple(reader.pages)
        except (OSError, PdfReadError, ValueError) as exc:
            raise AuthorityPackageError("authority source is not a readable PDF") from exc
        if not pages:
            raise AuthorityPackageError("authority PDF contains no pages")
        authority = authorities[authority_id]
        member = f"sources/{authority_id}.pdf"
        digest = hashlib.sha256(data).hexdigest()
        source_url = row.get("source_url", "").strip() or authority.get("source_url")
        sources.append(
            AuthoritySourceRecord(
                authority_id,
                str(authority.get("canonical_citation", "")),
                authority.get("case_name") if isinstance(authority.get("case_name"), str) else None,
                path.name,
                member,
                digest,
                len(pages),
                source_url if isinstance(source_url, str) and source_url else None,
            )
        )
        source_bytes[member] = data
        for page_number, page in enumerate(pages, start=1):
            text = page.extract_text() or ""
            page_rows.append(
                {
                    "authority_id": authority_id,
                    "page_number": page_number,
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                }
            )

    missing = tuple(sorted(set(authorities) - {source.authority_id for source in sources}))
    package_manifest = {
        "schema_version": 1,
        "brief_sha256": manifest.get("brief_sha256"),
        "sources": [asdict(source) for source in sources],
        "missing_authority_ids": missing,
        "verification_levels": [
            "citation-exists",
            "quotation-exact",
            "quotation-signals-complete",
            "characterization-supported",
        ],
    }
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{output.name}.", suffix=".tmp", dir=output.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("manifest.json", _json_bytes(package_manifest))
            archive.writestr(
                "pages.jsonl",
                b"".join(_json_bytes(row, newline=True) for row in page_rows),
            )
            archive.writestr("brief-authority-manifest.json", _json_bytes(manifest))
            for member, data in source_bytes.items():
                archive.writestr(member, data)
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise AuthorityPackageError("authority package failed its CRC check")
        temporary.chmod(0o600)
        os.replace(temporary, output)
        output.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return AuthorityPackageResult(
        _hash_path(output), len(sources), len(page_rows), missing
    )


def _load_manifest(path: Path) -> dict[str, object]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 10 * 1024 * 1024:
        raise AuthorityPackageError("authority manifest must be a regular file under 10 MiB")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AuthorityPackageError("authority manifest is invalid JSON") from exc
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != 1
        or not isinstance(value.get("authorities"), list)
    ):
        raise AuthorityPackageError("authority manifest has an unsupported schema")
    return value


def _load_intake(path: Path) -> dict[str, dict[str, str]]:
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise AuthorityPackageError("authority intake must be a regular CSV under 1 MiB")
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        raise AuthorityPackageError("authority intake is invalid CSV") from exc
    intake: dict[str, dict[str, str]] = {}
    for row in rows:
        authority_id = row.get("authority_id", "").strip()
        if not authority_id or authority_id in intake:
            raise AuthorityPackageError("authority intake IDs must be non-empty and unique")
        intake[authority_id] = row
    return intake


def _confined_source(bundle_dir: Path, value: str) -> Path:
    pure = PurePosixPath(value.replace("\\", "/"))
    if pure.is_absolute() or ".." in pure.parts:
        raise AuthorityPackageError("authority source path escapes the bundle")
    path = bundle_dir.joinpath(*pure.parts)
    if not path.is_file() or path.is_symlink() or path.suffix.lower() != ".pdf":
        raise AuthorityPackageError("authority source must be a regular PDF in the bundle")
    if not path.resolve().is_relative_to(bundle_dir.resolve()):
        raise AuthorityPackageError("authority source path escapes the bundle")
    return path


def _json_bytes(value: object, *, newline: bool = False) -> bytes:
    suffix = "\n" if newline else ""
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + suffix).encode()


def _hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()
