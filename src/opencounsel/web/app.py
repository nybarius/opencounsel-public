from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.datastructures import FormData, MutableHeaders, UploadFile
from starlette.formparsers import MultiPartException
from starlette.requests import Request
from starlette.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from opencounsel.demo import build_synthetic_demo
from opencounsel.source.authority_package import AuthorityPackageError
from opencounsel.source.pdf_roa import PdfRoaPackagingError, package_searchable_pdf
from opencounsel.templates.profiles import (
    FilingProfileError,
    get_bundled_filing_profile,
    list_bundled_filing_profiles,
)
from opencounsel.web.jobs import (
    JobManager,
    JobNotFoundError,
    JobReservation,
    SourceFinalizationError,
)
from opencounsel.web.link_finalization import (
    approve_link_disposition,
    prepare_link_disposition,
)

MAX_UPLOAD_BYTES = 100 * 1024 * 1024
STATIC_ROOT = Path(__file__).with_name("static")


class IntakeError(ValueError):
    pass


def create_app(
    *,
    root: Path | None = None,
    manager: JobManager | None = None,
    libreoffice: str = "libreoffice",
) -> Starlette:
    owned_manager = manager is None
    job_manager = manager or JobManager(
        root or _default_root(), libreoffice=libreoffice
    )

    @asynccontextmanager
    async def lifespan(app: Starlette) -> AsyncIterator[None]:
        app.state.jobs = job_manager
        yield
        if owned_manager or manager is not None:
            job_manager.close()

    app = Starlette(
        debug=False,
        routes=[
            Route("/", _home),
            Route("/healthz", _health),
            Route("/api/profiles", _profiles),
            Route("/api/jobs", _create_job, methods=["POST"]),
            Route("/api/jobs/{job_id}", _job, methods=["GET", "DELETE"]),
            Route(
                "/api/jobs/{job_id}/sources",
                _add_sources,
                methods=["POST"],
            ),
            Route(
                "/api/jobs/{job_id}/links",
                _approve_links,
                methods=["POST"],
            ),
            Route(
                "/api/jobs/{job_id}/artifacts/{artifact}",
                _artifact,
                methods=["GET"],
            ),
            Route("/api/demo", _demo, methods=["POST"]),
            Route("/api/explain", _explain, methods=["POST"]),
            Mount("/assets", app=StaticFiles(directory=STATIC_ROOT), name="assets"),
        ],
        lifespan=lifespan,
    )
    app.add_middleware(SecurityHeadersMiddleware)
    app.state.jobs = job_manager
    return app


async def _home(_request: Request) -> Response:
    try:
        body = (STATIC_ROOT / "index.html").read_text(encoding="utf-8")
    except OSError:
        return HTMLResponse("OpenCounsel interface assets are unavailable.", status_code=500)
    return HTMLResponse(body)


async def _health(_request: Request) -> Response:
    return JSONResponse({"status": "ready", "service": "opencounsel-web"})


async def _profiles(_request: Request) -> Response:
    profiles = list_bundled_filing_profiles()
    return JSONResponse(
        {
            "profiles": [
                {
                    "profile_id": profile.profile_id,
                    "jurisdiction": profile.jurisdiction,
                    "court": profile.court,
                    "document_type": profile.document_type,
                    "version": profile.version,
                    "last_verified": profile.last_verified.isoformat(),
                    "body_font_pt": profile.typography.body_min_pt,
                    "footnote_font_pt": profile.typography.footnote_min_pt,
                }
                for profile in profiles
            ]
        }
    )


async def _create_job(request: Request) -> Response:
    reservation: JobReservation | None = None
    form: FormData | None = None
    try:
        form = await request.form(
            max_files=2,
            max_fields=8,
            max_part_size=MAX_UPLOAD_BYTES,
        )
        brief = _upload(form, "brief")
        brief_name = _display_name(brief.filename)
        if Path(brief_name).suffix.lower() != ".docx":
            raise IntakeError("The brief must be a .docx file.")
        record_mode = _text(form, "record_mode", default="record")
        if record_mode not in {"record", "no-record"}:
            raise IntakeError("Select whether this filing uses a record package.")
        roa = _optional_upload(form, "roa")
        roa_name: str | None = None
        roa_suffix: str | None = None
        if record_mode == "record":
            if roa is None:
                raise IntakeError("The record file is required when this filing uses a record.")
            roa_name = _display_name(roa.filename)
            roa_suffix = Path(roa_name).suffix.lower()
            if roa_suffix not in {".zip", ".pdf"}:
                raise IntakeError("The record must be a .pdf file or mapped .zip package.")
        elif roa is not None:
            raise IntakeError("Do not upload a record when no record package is needed.")
        profile_id = _text(form, "profile")
        get_bundled_filing_profile(profile_id)

        jobs = _jobs(request)
        reservation = jobs.reserve(
            profile_id=profile_id,
            brief_name=brief_name,
            roa_name=roa_name,
            record_mode=record_mode,
        )
        await _save_upload(brief, reservation.context.brief_path)
        if roa is not None and reservation.context.roa_path is not None and roa_suffix == ".zip":
            await _save_upload(roa, reservation.context.roa_path)
        elif roa is not None and reservation.context.roa_path is not None:
            await _save_upload(roa, reservation.record_pdf_path)
            try:
                first_record_page = int(_text(form, "first_record_page", default="1"))
            except ValueError as exc:
                raise IntakeError("The first record page must be a positive integer.") from exc
            package_searchable_pdf(
                reservation.record_pdf_path,
                reservation.context.roa_path,
                first_record_page=first_record_page,
                numbering_verified=_checked(form, "numbering_verified"),
            )
        jobs.submit(reservation.context)
        return JSONResponse(
            {"job_id": reservation.context.job_id, "status": "queued"},
            status_code=202,
        )
    except (IntakeError, FilingProfileError, PdfRoaPackagingError) as exc:
        if reservation is not None:
            _jobs(request).mark_failed(reservation.context, str(exc))
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
    except (ValueError, OSError, MultiPartException):
        if reservation is not None:
            _jobs(request).mark_failed(reservation.context, "Input files could not be accepted.")
        return JSONResponse(
            {"status": "error", "error": "Input files could not be accepted."},
            status_code=400,
        )
    finally:
        if form is not None:
            await form.close()


async def _job(request: Request) -> Response:
    try:
        if request.method == "DELETE":
            _jobs(request).delete(request.path_params["job_id"])
            return Response(status_code=204)
        return JSONResponse(_jobs(request).snapshot(request.path_params["job_id"]))
    except JobNotFoundError:
        return JSONResponse(
            {"status": "error", "error": "Job not found."}, status_code=404
        )
    except ValueError as exc:
        return JSONResponse(
            {"status": "error", "error": str(exc)}, status_code=409
        )


async def _artifact(request: Request) -> Response:
    try:
        artifact = _jobs(request).artifact(
            request.path_params["job_id"], request.path_params["artifact"]
        )
    except JobNotFoundError:
        return JSONResponse(
            {"status": "error", "error": "Artifact not found."}, status_code=404
        )
    disposition = (
        "inline"
        if request.query_params.get("inline") == "1" and artifact.media_type == "application/pdf"
        else "attachment"
    )
    return FileResponse(
        artifact.path,
        media_type=artifact.media_type,
        filename=artifact.filename,
        content_disposition_type=disposition,
    )


async def _add_sources(request: Request) -> Response:
    form: FormData | None = None
    job_id = request.path_params["job_id"]
    reserved = False
    try:
        form = await request.form(
            max_files=100,
            max_fields=200,
            max_part_size=MAX_UPLOAD_BYTES,
        )
        raw_ids = form.getlist("authority_id")
        raw_sources = form.getlist("source")
        if len(raw_sources) > 1 and len(raw_ids) < len(raw_sources):
            raise IntakeError("Duplicate or missing authority IDs are not allowed.")
        if not raw_ids or not raw_sources or len(raw_ids) != len(raw_sources):
            raise IntakeError(
                "Each source PDF must identify one declared authority; "
                "duplicate IDs are not allowed."
            )
        if not all(isinstance(value, str) and value.strip() for value in raw_ids):
            raise IntakeError("Each source PDF must identify one declared authority.")
        if not all(isinstance(value, UploadFile) for value in raw_sources):
            raise IntakeError("Each declared authority requires a source PDF.")
        authority_ids = [value.strip() for value in raw_ids if isinstance(value, str)]
        if len(set(authority_ids)) != len(authority_ids):
            raise IntakeError("Duplicate authority IDs are not allowed in one request.")
        sources = [value for value in raw_sources if isinstance(value, UploadFile)]
        for source in sources:
            if Path(_display_name(source.filename)).suffix.lower() != ".pdf":
                raise IntakeError("Authority sources must be readable PDF files.")

        jobs = _jobs(request)
        outputs = jobs.reserve_source_uploads(job_id, authority_ids)
        reserved = True
        for authority_id, source in zip(authority_ids, sources, strict=True):
            await _save_upload(source, outputs[authority_id])
        jobs.finalize_sources(job_id, authority_ids)
        return JSONResponse(prepare_link_disposition(jobs, job_id, authority_ids))
    except JobNotFoundError:
        return JSONResponse(
            {"status": "error", "error": "Job not found."}, status_code=404
        )
    except (IntakeError, SourceFinalizationError, AuthorityPackageError) as exc:
        if reserved:
            _jobs(request).discard_source_uploads(job_id)
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
    except (ValueError, OSError, MultiPartException):
        if reserved:
            _jobs(request).discard_source_uploads(job_id)
        return JSONResponse(
            {"status": "error", "error": "Source files could not be accepted."},
            status_code=400,
        )
    finally:
        if form is not None:
            await form.close()


async def _approve_links(request: Request) -> Response:
    job_id = request.path_params["job_id"]
    try:
        payload = await request.json()
        if not isinstance(payload, dict):
            raise IntakeError("Link approval must be a JSON object.")
        raw_ids = payload.get("link_ids")
        if not isinstance(raw_ids, list) or not raw_ids:
            raise IntakeError("Select at least one declared link candidate.")
        if not all(isinstance(value, str) and value.strip() for value in raw_ids):
            raise IntakeError("Each approved link must use a declared link ID.")
        link_ids = [value.strip() for value in raw_ids if isinstance(value, str)]
        if len(set(link_ids)) != len(link_ids):
            raise IntakeError("Duplicate link IDs are not allowed.")
        return JSONResponse(approve_link_disposition(_jobs(request), job_id, link_ids))
    except JobNotFoundError:
        return JSONResponse(
            {"status": "error", "error": "Job not found."}, status_code=404
        )
    except (IntakeError, SourceFinalizationError, AuthorityPackageError) as exc:
        return JSONResponse({"status": "error", "error": str(exc)}, status_code=400)
    except (json.JSONDecodeError, TypeError, ValueError):
        return JSONResponse(
            {"status": "error", "error": "Link approval could not be accepted."},
            status_code=400,
        )


async def _explain(request: Request) -> Response:
    """Why did it decide that: the lift of a ledgered correction's class, never a model call."""
    from opencounsel import explain as explain_lift

    try:
        record = await request.json()
        lifted = explain_lift.explain_record(record if isinstance(record, dict) else {})
    except ValueError as error:
        return JSONResponse({"error": str(error)}, status_code=400)
    return JSONResponse(
        {"class": list(lifted["class"]), "prose": lifted["prose"], "witness": lifted["witness"]}
    )


async def _demo(request: Request) -> Response:
    jobs = _jobs(request)
    reservation = jobs.reserve(
        profile_id="fed-sdny-edny-motion-memorandum",
        brief_name="synthetic-appellant-brief.docx",
        roa_name=None,
        record_mode="no-record",
        demo=True,
    )
    try:
        brief, _roa = build_synthetic_demo(reservation.context.inbox_dir)
        if reservation.context.roa_path is not None or brief != reservation.context.brief_path:
            raise RuntimeError("synthetic inputs were written outside the reserved paths")
        jobs.submit(reservation.context)
    except Exception:
        jobs.mark_failed(
            reservation.context,
            "The synthetic demonstration could not be prepared.",
        )
        return JSONResponse(
            {"status": "error", "error": "Synthetic demonstration failed."},
            status_code=500,
        )
    return JSONResponse(
        {"job_id": reservation.context.job_id, "status": "queued"},
        status_code=202,
    )


def _jobs(request: Request) -> JobManager:
    return request.app.state.jobs


def _upload(form: FormData, field: str) -> UploadFile:
    value = form.get(field)
    if not isinstance(value, UploadFile):
        raise IntakeError(f"The {field} file is required.")
    return value


def _optional_upload(form: FormData, field: str) -> UploadFile | None:
    value = form.get(field)
    if value is None:
        return None
    if not isinstance(value, UploadFile):
        raise IntakeError(f"The {field} file could not be accepted.")
    return value


def _text(form: FormData, field: str, *, default: str | None = None) -> str:
    value = form.get(field, default)
    if not isinstance(value, str) or not value.strip():
        raise IntakeError(f"The {field.replace('_', ' ')} value is required.")
    return value.strip()


def _checked(form: FormData, field: str) -> bool:
    value = form.get(field)
    return isinstance(value, str) and value.casefold() in {"1", "true", "yes", "on"}


def _display_name(value: str | None) -> str:
    name = Path(value or "").name
    name = "".join(character for character in name if character.isprintable())[:255]
    if not name:
        raise IntakeError("Uploaded files must have a filename.")
    return name


async def _save_upload(upload: UploadFile, output: Path) -> None:
    descriptor = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    size = 0
    try:
        with os.fdopen(descriptor, "wb") as target:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise IntakeError("Uploaded files must not exceed 100 MiB each.")
                target.write(chunk)
        output.chmod(0o600)
    except Exception:
        output.unlink(missing_ok=True)
        raise


def _default_root() -> Path:
    configured = os.environ.get("OPENCOUNSEL_WEB_ROOT")
    if configured:
        return Path(configured)
    return Path.home() / ".local" / "share" / "opencounsel" / "web"


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        async def secure_send(message: Message) -> None:
            if message.get("type") == "http.response.start":
                headers = MutableHeaders(scope=message)
                inline_pdf_artifact = (
                    scope.get("endpoint") is _artifact
                    and headers.get("content-type") == "application/pdf"
                    and headers.get("content-disposition", "").startswith("inline;")
                )
                headers["cache-control"] = "no-store"
                headers["content-security-policy"] = _csp(
                    frame_ancestors="'self'" if inline_pdf_artifact else "'none'"
                )
                headers["referrer-policy"] = "no-referrer"
                headers["x-content-type-options"] = "nosniff"
                headers["x-frame-options"] = (
                    "SAMEORIGIN" if inline_pdf_artifact else "DENY"
                )
            await send(message)

        await self.app(scope, receive, secure_send)


def _csp(*, frame_ancestors: str = "'none'") -> str:
    return (
        "default-src 'self'; base-uri 'none'; form-action 'self'; "
        f"frame-ancestors {frame_ancestors}; "
        "frame-src 'self'; img-src 'self' data:; object-src 'self'; script-src 'self'; "
        "style-src 'self'"
    )


__all__ = ["create_app"]
