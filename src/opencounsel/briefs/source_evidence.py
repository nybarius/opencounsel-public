from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from opencounsel.briefs.links import AuthorityResolution


class SourceEvidenceError(ValueError):
    """Raised when URL verification evidence cannot be obtained or stored safely."""


@dataclass(frozen=True, slots=True)
class UrlEvidence:
    url: str
    checked_at: str
    status_code: int
    final_url: str
    content_type: str | None
    valid: bool


def verify_resolution_urls(
    resolutions: tuple[AuthorityResolution, ...],
    cache_path: Path,
    *,
    max_age: timedelta = timedelta(days=7),
    opener: Callable[..., object] = urlopen,
    now: datetime | None = None,
) -> tuple[AuthorityResolution, ...]:
    checked_at = now or datetime.now(UTC)
    cache = _load_cache(cache_path)
    evidence_by_url = {item.url: item for item in cache}
    updated: dict[str, UrlEvidence] = dict(evidence_by_url)
    output: list[AuthorityResolution] = []
    for resolution in resolutions:
        if not resolution.url:
            output.append(replace(resolution, status="unverified"))
            continue
        evidence = evidence_by_url.get(resolution.url)
        if evidence is None or _expired(evidence, checked_at, max_age):
            evidence = _check_url(resolution.url, checked_at, opener)
            updated[resolution.url] = evidence
        output.append(replace(resolution, status="verified" if evidence.valid else "unverified"))
    _write_cache(cache_path, tuple(sorted(updated.values(), key=lambda item: item.url)))
    return tuple(output)


def _check_url(
    url: str,
    checked_at: datetime,
    opener: Callable[..., object],
) -> UrlEvidence:
    request = Request(url, method="HEAD", headers={"User-Agent": "OpenCounsel/0.1 link-check"})
    try:
        response = opener(request, timeout=15)
    except HTTPError as exc:
        if exc.code not in {405, 501}:
            return UrlEvidence(url, checked_at.isoformat(), exc.code, url, None, False)
        request = Request(
            url,
            method="GET",
            headers={"Range": "bytes=0-0", "User-Agent": "OpenCounsel/0.1 link-check"},
        )
        try:
            response = opener(request, timeout=15)
        except (HTTPError, URLError, TimeoutError, OSError) as fallback_exc:
            status = fallback_exc.code if isinstance(fallback_exc, HTTPError) else 0
            return UrlEvidence(url, checked_at.isoformat(), status, url, None, False)
    except (URLError, TimeoutError, OSError):
        return UrlEvidence(url, checked_at.isoformat(), 0, url, None, False)
    status = int(getattr(response, "status", 200))
    final_url = str(getattr(response, "url", url))
    headers = getattr(response, "headers", {})
    content_type = headers.get("Content-Type") if hasattr(headers, "get") else None
    return UrlEvidence(
        url,
        checked_at.isoformat(),
        status,
        final_url,
        content_type,
        200 <= status < 400 and final_url.startswith("https://"),
    )


def _expired(evidence: UrlEvidence, now: datetime, max_age: timedelta) -> bool:
    try:
        checked_at = datetime.fromisoformat(evidence.checked_at)
    except ValueError:
        return True
    if checked_at.tzinfo is None:
        checked_at = checked_at.replace(tzinfo=UTC)
    return now - checked_at > max_age


def _load_cache(path: Path) -> tuple[UrlEvidence, ...]:
    if not path.exists():
        return ()
    if not path.is_file() or path.is_symlink() or path.stat().st_size > 1024 * 1024:
        raise SourceEvidenceError("source evidence cache must be a regular file under 1 MiB")
    try:
        values = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(values, dict)
            or values.get("schema_version") != 1
            or not isinstance(values.get("evidence"), list)
        ):
            raise ValueError
        return tuple(UrlEvidence(**item) for item in values["evidence"])
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceEvidenceError("source evidence cache is invalid") from exc


def _write_cache(path: Path, evidence: tuple[UrlEvidence, ...]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(
                {"schema_version": 1, "evidence": [asdict(item) for item in evidence]},
                stream,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
        temporary.chmod(0o600)
        os.replace(temporary, path)
        path.chmod(0o600)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
