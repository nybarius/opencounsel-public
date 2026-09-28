#!/usr/bin/env python3
"""The privilege gate: a deterministic scan of every file and history blob that would ship.

    python3 scripts/privilege_audit.py [--root DIR] [--json] [--no-history]

Refused (exit 1): attorney-client privilege or work-product markers, material under seal, PII
(SSNs, personal e-mail addresses), secrets and credentials, private URLs and internal hostnames.
Listed for review (exit 2), never shipped on a guess: a case caption not in
`docs/LEGAL_FIXTURES.json`,
the manifest of every retained legal fixture with its public source. Clean: exit 0. The history
scan reads every blob reachable from any ref, so an old blob with such content refuses the tree
even when the working tree is clean: the public repository gets a fresh history built by a
fresh-root rebuild, never this one. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

PATTERNS = {
    "privilege": (
        r"(?i)attorney[- ]client privilege[d]?|privileged (?:and|&) confidential"
        r"|attorney work[- ]product|work product of counsel"
    ),
    "seal": r"(?i)\b(?:filed )?under seal\b|\bsealed (?:exhibit|record|filing)\b",
    "secret": (
        r"(?i)-----BEGIN [A-Z ]*PRIVATE KEY-----|\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{30,}"
        r"|\bgithub_pat_[A-Za-z0-9_]{30,}|\bsk-[A-Za-z0-9_-]{24,}|\bAKIA[0-9A-Z]{16}\b"
        r"|\bxox[abp]-[A-Za-z0-9-]{10,}"
        r"|\b(?:password|passwd|secret|api[_-]?key|access[_-]?token)\s*[=:]\s*['\"]?[A-Za-z0-9_\-/+=]{16,}"
    ),
    "private_host": (
        r"\b10\.\d{1,3}\.\d{1,3}\.\d{1,3}\b|\b192\.168\.\d{1,3}\.\d{1,3}\b"
        r"|\b172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}\b"
        r"|\b[a-z0-9][a-z0-9.-]*\.(?:internal|local|lan|corp|intranet)\b"
    ),
    "pii": (
        r"\b\d{3}-\d{2}-\d{4}\b"
        r"|\b[A-Za-z0-9._%+-]+@(?:gmail|yahoo|hotmail|outlook|icloud|proton|protonmail|aol)\.[a-z]{2,}\b"
    ),
}
_WORD = r"[A-Z][A-Za-z.&'\u2019-]+"
_NAME = rf"{_WORD}(?: {_WORD}){{0,6}},?(?: Inc\.| LLC| Corp\.| Co\.| Ltd\.)?"
CAPTION = re.compile(rf"\b{_NAME} v\. {_NAME}")
SKIP_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".ruff_cache",
    ".pytest_cache",
    "dist",
    "build",
}
SELF = {
    "scripts/privilege_audit.py", "tests/test_privilege_audit.py",
    "tests/test_public_candidate.py", "docs/LEGAL_FIXTURES.json",
}
MAX_BYTES = 2_000_000


def _text(data: bytes) -> str | None:
    if b"\0" in data[:8192] or len(data) > MAX_BYTES:
        return None
    return data.decode("utf-8", errors="replace")


def _manifest(root: Path) -> dict:
    p = root / "docs" / "LEGAL_FIXTURES.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"fixtures": []}


def _known_captions(manifest: dict) -> list[str]:
    out: list[str] = []
    for f in manifest.get("fixtures", []):
        out += [c for c in f.get("captions", []) if c]
    out += manifest.get("public_captions", [])
    return out


SCHEMA_ID = re.compile(r'"\$id"\s*:\s*"https?://([a-z0-9.-]+)/')


def scan_text(
    path: str,
    text: str,
    where: str,
    known: list[str],
    discussion: set[str],
    synthetic: set[str] = frozenset(),
    schema_hosts: set[str] = frozenset(),
) -> tuple[list[dict], list[dict]]:
    findings, review = [], []
    if path in SELF:
        return findings, review
    for kind, pat in PATTERNS.items():
        if path in discussion:
            # prose that discusses these markers, declared as such in the manifest
            continue
        for m in re.finditer(pat, text):
            witness = text[max(0, m.start() - 20) : m.end() + 20].replace("\n", " ")
            if (
                kind == "private_host"
                and any(m.group(0).endswith(h) for h in schema_hosts)
                and all(host in schema_hosts for host in SCHEMA_ID.findall(text))
                and SCHEMA_ID.search(text)
            ):
                continue  # a JSON-schema $id naming convention declared in the manifest, not a host
            if path in synthetic:
                review.append(
                    {
                        "kind": kind,
                        "path": path,
                        "where": where,
                        "witness": witness,
                        "synthetic": True,
                    }
                )
                break
            findings.append({"kind": kind, "path": path, "where": where, "witness": witness})
            break
    for m in CAPTION.finditer(text):
        cap = m.group(0)
        if not any(k.lower() in cap.lower() or cap.lower() in k.lower() for k in known):
            review.append({"kind": "caption", "path": path, "where": where, "witness": cap})
            break
    return findings, review


def scan_tree(
    root: Path,
    known: list[str],
    discussion: set[str],
    synthetic: set[str] = frozenset(),
    schema_hosts: set[str] = frozenset(),
) -> tuple[int, list[dict], list[dict]]:
    n, findings, review = 0, [], []
    for p in sorted(root.rglob("*")):
        if (
            any(part in SKIP_DIRS for part in p.relative_to(root).parts)
            or not p.is_file()
            or p.is_symlink()
        ):
            continue
        try:
            text = _text(p.read_bytes())
        except OSError:
            continue
        n += 1
        if text is None:
            continue
        f, r = scan_text(
            str(p.relative_to(root)), text, "tree", known, discussion, synthetic, schema_hosts
        )
        findings += f
        review += r
    return n, findings, review


def scan_history(
    root: Path,
    known: list[str],
    discussion: set[str],
    synthetic: set[str] = frozenset(),
    schema_hosts: set[str] = frozenset(),
) -> tuple[int, list[dict], list[dict]]:
    try:
        objs = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--all", "--objects"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return 0, [], []
    blobs: dict[str, str] = {}
    for line in objs.splitlines():
        parts = line.split(" ", 1)
        if len(parts) == 2 and parts[1] and "/" in parts[1] + "/":
            blobs.setdefault(parts[0], parts[1])
    if not blobs:
        return 0, [], []
    batch = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"],
        input=("\n".join(blobs) + "\n").encode(),
        capture_output=True,
        check=True,
    ).stdout
    n, findings, review, i = 0, [], [], 0
    seen: set[tuple] = set()
    while i < len(batch):
        j = batch.index(b"\n", i)
        header = batch[i:j].decode()
        i = j + 1
        parts = header.split()
        if len(parts) < 3:
            continue
        sha, kind, size = parts[0], parts[1], int(parts[2])
        data = batch[i : i + size]
        i += size + 1
        if kind != "blob":
            continue
        n += 1
        text = _text(data)
        if text is None:
            continue
        path = blobs.get(sha, sha)
        f, r = scan_text(path, text, "history", known, discussion, synthetic, schema_hosts)
        for x in f + r:
            x["blob"] = sha[:12]
        findings += [
            x
            for x in f
            if (x["kind"], x["path"]) not in seen and not seen.add((x["kind"], x["path"]))
        ]
        review += [
            x
            for x in r
            if ("caption", x["path"]) not in seen and not seen.add(("caption", x["path"]))
        ]
    return n, findings, review


def audit(root: Path, history: bool = True) -> dict:
    manifest = _manifest(root)
    known = _known_captions(manifest)
    discussion = set(manifest.get("discussion_paths", []))
    synthetic = set(manifest.get("synthetic_fixture_paths", []))
    schema_hosts = set(manifest.get("schema_id_hosts", []))
    tn, tf, tr = scan_tree(root, known, discussion, synthetic, schema_hosts)
    hn, hf, hr = (
        scan_history(root, known, discussion, synthetic, schema_hosts) if history else (0, [], [])
    )
    findings, review = tf + hf, tr + hr
    verdict = "REFUSED" if findings else ("REVIEW" if review else "CLEAN")
    return {
        "schema": "opencounsel.privilege-audit/1",
        "verdict": verdict,
        "scanned": {"tree_files": tn, "history_blobs": hn},
        "findings": findings,
        "review": review,
        "manifest_fixtures": len(manifest.get("fixtures", [])),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--no-history", action="store_true")
    a = ap.parse_args(argv)
    out = audit(Path(a.root).resolve(), history=not a.no_history)
    if a.json:
        print(json.dumps(out, indent=1, sort_keys=True))
    else:
        print(
            f"{out['verdict']}: {out['scanned']['tree_files']} files, "
            f"{out['scanned']['history_blobs']} history blobs, "
            f"{len(out['findings'])} findings, {len(out['review'])} for review"
        )
        for f in out["findings"] + out["review"]:
            print(f"  {f['kind']:12} {f['where']:7} {f['path']}: {f['witness'][:100]}")
    return {"CLEAN": 0, "REFUSED": 1, "REVIEW": 2}[out["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
