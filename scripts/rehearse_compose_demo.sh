#!/bin/sh
set -eu

REPORT_PATH=${1:-compose-rehearsal-report.json}
VOLUME_NAME=opencounsel_opencounsel-data

compose() {
  docker compose "$@"
}

cleanup() {
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}

trap cleanup EXIT HUP INT TERM
cleanup
if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo "clean-state rehearsal could not remove the existing data volume" >&2
  exit 1
fi

build_started=$(date +%s)
compose build
build_seconds=$(( $(date +%s) - build_started ))

ready_started=$(date +%s)
compose up --detach
ready=0
attempt=0
while [ "$attempt" -lt 90 ]; do
  if compose exec -T opencounsel python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/healthz', timeout=2).read()" >/dev/null 2>&1; then
    ready=1
    break
  fi
  attempt=$((attempt + 1))
  sleep 1
done
if [ "$ready" -ne 1 ]; then
  compose logs opencounsel >&2
  echo "OpenCounsel did not become ready" >&2
  exit 1
fi
readiness_seconds=$(( $(date +%s) - ready_started ))

workflow_result=$(compose exec -T opencounsel python - <<'PY'
from __future__ import annotations

import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from pypdf import PdfReader

BASE_URL = "http://127.0.0.1:8765"
DATA_ROOT = Path("/home/opencounsel/data")
SOURCE_NAMES = {
    "101 u.s. 99": "baker-v-selden.pdf",
    "464 u.s. 417": "sony-v-universal.pdf",
    "556 u.s. 662": "ashcroft-v-iqbal.pdf",
    "804 f.3d 202": "authors-guild-v-google.pdf",
}


class Client:
    def request(
        self,
        path: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, bytes]:
        request = urllib.request.Request(
            BASE_URL + path,
            data=data,
            headers=headers or {},
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                status = response.status
                body = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            body = exc.read()
        if status not in expected:
            raise RuntimeError(
                f"{method} {path} returned {status}: {body.decode('utf-8', errors='replace')}"
            )
        return status, body

    def post(
        self,
        path: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        expected: tuple[int, ...] = (200,),
    ) -> tuple[int, bytes]:
        return self.request(
            path,
            method="POST",
            data=data,
            headers=headers,
            expected=expected,
        )


def json_body(body: bytes) -> dict[str, object]:
    payload = json.loads(body)
    if not isinstance(payload, dict):
        raise RuntimeError("OpenCounsel returned a non-object JSON response")
    return payload


def artifact(client: Client, job_id: str, name: str) -> bytes:
    _status, body = client.request(f"/api/jobs/{job_id}/artifacts/{name}")
    return body


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def source_name(citation: str) -> str:
    folded = citation.casefold()
    for marker, filename in SOURCE_NAMES.items():
        if marker in folded:
            return filename
    raise RuntimeError(f"no prepared public source is mapped for {citation!r}")


def multipart_sources(job_id: str, sources: list[dict[str, object]]) -> tuple[bytes, str]:
    boundary = f"opencounsel-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for source in sources:
        authority_id = source.get("authority_id")
        citation = source.get("citation")
        if not isinstance(authority_id, str) or not isinstance(citation, str):
            raise RuntimeError("the source manifest omitted an authority ID or citation")
        filename = source_name(citation)
        path = DATA_ROOT / job_id / "inbox" / "authority-sources" / filename
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"prepared authority source is unavailable: {filename}")
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                b'Content-Disposition: form-data; name="authority_id"\r\n\r\n',
                authority_id.encode(),
                b"\r\n",
                f"--{boundary}\r\n".encode(),
                (
                    'Content-Disposition: form-data; name="source"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: application/pdf\r\n\r\n",
                path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), boundary


def print_publication_diagnostics(job_id: str) -> None:
    job_root = DATA_ROOT / job_id
    for front_matter in job_root.rglob("front-matter.json"):
        try:
            payload = json.loads(front_matter.read_text(encoding="utf-8"))
            headings = [item.get("heading") for item in payload.get("toc", [])]
        except Exception as exc:
            print(f"diagnostic front matter error: {exc}", file=sys.stderr)
        else:
            print(f"diagnostic TOC headings: {headings!r}", file=sys.stderr)
    for pdf in job_root.rglob("published.pdf"):
        try:
            pages = [page.extract_text() or "" for page in PdfReader(pdf).pages]
        except Exception as exc:
            print(f"diagnostic PDF error: {exc}", file=sys.stderr)
        else:
            for index, text in enumerate(pages, start=1):
                print(f"diagnostic PDF page {index}: {text!r}", file=sys.stderr)


client = Client()
_status, body = client.post("/api/demo", expected=(202,))
created = json_body(body)
job_id = created.get("job_id")
if not isinstance(job_id, str):
    raise RuntimeError("the demo response omitted its job ID")

for _attempt in range(360):
    _status, body = client.request(f"/api/jobs/{job_id}")
    state = json_body(body)
    if state.get("status") in {"completed", "failed"}:
        break
    time.sleep(0.5)
else:
    raise RuntimeError("the first processing pass did not complete")
if state.get("status") != "completed":
    print_publication_diagnostics(job_id)
    raise RuntimeError(f"the first processing pass failed: {state.get('error')}")
if state.get("record_mode") != "no-record" or state.get("roa_name") is not None:
    raise RuntimeError("the public demo did not use the explicit no-record path")

first_docx = artifact(client, job_id, "document")
first_pdf = artifact(client, job_id, "pdf")
first_package = artifact(client, job_id, "package")
first_hashes = {
    "document_sha256": digest(first_docx),
    "pdf_sha256": digest(first_pdf),
    "package_sha256": digest(first_package),
}

raw_sources = state.get("sources")
if not isinstance(raw_sources, list) or not all(
    isinstance(source, dict) for source in raw_sources
):
    raise RuntimeError("the public demo returned an invalid source manifest")
sources = [
    source
    for source in raw_sources
    if source.get("status") == "source-copy-required"
]
if len(sources) != 4:
    raise RuntimeError(
        "the public demo did not declare exactly four authority upload slots"
    )
body, boundary = multipart_sources(job_id, sources)
_status, body = client.post(
    f"/api/jobs/{job_id}/sources",
    data=body,
    headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
)
finalized = json_body(body)
verification = finalized.get("source_verification")
if not isinstance(verification, dict):
    raise RuntimeError("the second pass did not produce source-verification evidence")
if verification.get("citation_confirmed_count") != 4:
    raise RuntimeError("the second pass did not confirm all four authority identities")
if verification.get("quotation_failure_count") != 0:
    raise RuntimeError("the second pass reported a quotation failure")

link_disposition = finalized.get("link_disposition")
if not isinstance(link_disposition, dict):
    raise RuntimeError("the second pass did not classify embedded source links")
raw_links = link_disposition.get("links")
if not isinstance(raw_links, list) or not all(
    isinstance(link, dict) for link in raw_links
):
    raise RuntimeError("the second pass returned an invalid link disposition")
eligible_links = [
    link
    for link in raw_links
    if link.get("classification") == "durable-candidate"
    and link.get("approval_status") == "pending"
]
if len(eligible_links) != 1 or link_disposition.get("approved_link_count") != 0:
    raise RuntimeError("the public demo did not expose one unapproved durable link")
link_id = eligible_links[0].get("link_id")
if not isinstance(link_id, str):
    raise RuntimeError("the durable link candidate omitted its stable ID")
_status, body = client.post(
    f"/api/jobs/{job_id}/links",
    data=json.dumps({"link_ids": [link_id]}).encode(),
    headers={"Content-Type": "application/json"},
)
approved = json_body(body)
approved_disposition = approved.get("link_disposition")
if not isinstance(approved_disposition, dict):
    raise RuntimeError("link approval did not return a disposition")
if approved_disposition.get("approved_link_count") != 1:
    raise RuntimeError("the eligible durable link was not affirmatively approved")
approved_links = approved_disposition.get("links")
if not isinstance(approved_links, list) or any(
    isinstance(link, dict)
    and link.get("classification") != "durable-candidate"
    and link.get("approval_status") == "approved"
    for link in approved_links
):
    raise RuntimeError("an ineligible embedded link was approved")
linked_docx = artifact(client, job_id, "linked-document")
linked_pdf = artifact(client, job_id, "linked-pdf")
if not linked_docx.startswith(b"PK") or not linked_pdf.startswith(b"%PDF"):
    raise RuntimeError("link approval did not create separate DOCX and PDF artifacts")

second_docx = artifact(client, job_id, "document")
second_pdf = artifact(client, job_id, "pdf")
if second_docx != first_docx or second_pdf != first_pdf:
    raise RuntimeError("source finalization mutated a first-pass filing artifact")
final_package = artifact(client, job_id, "final-package")
if not final_package.startswith(b"PK"):
    raise RuntimeError("the final review package is not a ZIP archive")

client.request(f"/api/jobs/{job_id}", method="DELETE", expected=(204,))
client.request(f"/api/jobs/{job_id}", expected=(404,))
if (DATA_ROOT / job_id).exists():
    raise RuntimeError("job deletion left local matter artifacts behind")

print(
    json.dumps(
        {
            "job_id": job_id,
            "record_mode": "no-record",
            "declared_authority_count": len(sources),
            "citation_confirmed_count": verification["citation_confirmed_count"],
            "quotation_failure_count": verification["quotation_failure_count"],
            "eligible_link_count": len(eligible_links),
            "approved_link_count": approved_disposition["approved_link_count"],
            "linked_artifacts_created": True,
            "first_pass_hashes": first_hashes,
            "first_pass_immutable": True,
            "final_package_sha256": digest(final_package),
            "job_deleted": True,
        },
        sort_keys=True,
    )
)
PY
)

cleanup
if docker volume inspect "$VOLUME_NAME" >/dev/null 2>&1; then
  echo "clean-state rehearsal left the data volume behind" >&2
  exit 1
fi
trap - EXIT HUP INT TERM

report_dir=$(dirname "$REPORT_PATH")
mkdir -p "$report_dir"
printf '{"build_seconds":%s,"readiness_seconds":%s,"volume_removed":true,"workflow":%s}\n' \
  "$build_seconds" "$readiness_seconds" "$workflow_result" > "$REPORT_PATH"
cat "$REPORT_PATH"
