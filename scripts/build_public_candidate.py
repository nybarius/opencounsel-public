#!/usr/bin/env python3
"""Push an audited tree to a candidate ref, without publishing private ancestry."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path

from privilege_audit import audit

MESSAGE = "OpenCounsel audited public candidate"


def _git(root: Path, *args: str, env: dict[str, str] | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(root), *args], env=env, check=True, capture_output=True, text=True
    ).stdout.strip()


def build(root: Path, ref: str) -> dict:
    full_ref = "refs/heads/" + ref
    if not ref.startswith("public/") or ref == "public/":
        raise ValueError("only a public/ candidate ref is allowed")
    _git(root, "check-ref-format", full_ref)
    with tempfile.TemporaryDirectory(prefix="opencounsel-candidate-") as temporary:
        scratch = Path(temporary)
        env = dict(os.environ, GIT_INDEX_FILE=str(scratch / "index"))
        _git(root, "read-tree", "HEAD", env=env)
        _git(root, "add", "-A", env=env)
        tree = _git(root, "write-tree", env=env)
        snapshot = scratch / "tree"
        snapshot.mkdir()
        entries = subprocess.run(
            ["git", "-C", str(root), "ls-tree", "-rz", tree],
            check=True, capture_output=True,
        ).stdout
        for entry in entries.split(b"\0"):
            if not entry:
                continue
            header, name = entry.split(b"\t", 1)
            mode, kind, sha = header.decode().split()
            if mode not in {"100644", "100755"} or kind != "blob":
                raise ValueError("candidate contains a symlink or non-file entry")
            target = snapshot / os.fsdecode(name)
            if not target.resolve().is_relative_to(snapshot):
                raise ValueError("candidate path escapes the snapshot")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(subprocess.run(
                ["git", "-C", str(root), "cat-file", "blob", sha],
                check=True, capture_output=True,
            ).stdout)
            target.chmod(int(mode, 8) & 0o777)
        report = audit(snapshot, history=False)
        out = {
            "schema": "opencounsel.public-candidate/1", "pushed": False,
            "audit": report["verdict"], "tree": tree, "ref": full_ref,
            "findings": report["findings"], "review": report["review"],
        }
        manifest = json.loads((snapshot / "docs" / "LEGAL_FIXTURES.json").read_text())
        confirmed = manifest.get("operator_confirmed_reviews", [])
        accepted_review = report["verdict"] == "REVIEW" and all(
            any(
                all(
                    confirmation.get(key) == item[key]
                    for key in ("kind", "path", "where", "witness")
                )
                and confirmation.get("confirmed_by") == "operator"
                and bool(confirmation.get("confirmed_at"))
                and confirmation.get("sha256") == hashlib.sha256(
                    (snapshot / item["path"]).read_bytes()
                ).hexdigest()
                for confirmation in confirmed if isinstance(confirmation, dict)
            )
            for item in report["review"]
        )
        if report["verdict"] != "CLEAN" and not accepted_review:
            return dict(out, reason="audit:" + report["verdict"])

        # A failed remote read is never an absent branch.
        remote = subprocess.run(
            ["git", "-C", str(root), "ls-remote", "--exit-code", "--heads", "origin", full_ref],
            check=False, capture_output=True, text=True,
        )
        if remote.returncode not in {0, 2}:
            raise ValueError("candidate remote is UNOBSERVED")
        parent = remote.stdout.split()[0] if remote.returncode == 0 else None
        if parent:
            _git(root, "fetch", "--no-tags", "origin", parent)
            for commit in _git(root, "rev-list", parent).splitlines():
                if _git(root, "show", "-s", "--format=%s", commit) != MESSAGE:
                    raise ValueError("remote candidate contains unrecognized ancestry")
                if len(_git(root, "rev-list", "--parents", "-n", "1", commit).split()) > 2:
                    raise ValueError("remote candidate contains merged ancestry")
            if _git(root, "rev-parse", parent + "^{tree}") == tree:
                return dict(out, reason="unchanged", commit=parent, parent=parent)
        args = ["commit-tree", tree, "-m", MESSAGE]
        if parent:
            args += ["-p", parent]
        commit = _git(root, *args)
        # Plain push rejects a racing non-fast-forward; never rewrite the remote.
        _git(root, "push", "origin", commit + ":" + full_ref)
        return dict(out, pushed=True, commit=commit, parent=parent)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--ref", default="public/candidate")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    try:
        out = build(args.root.resolve(), args.ref)
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        out = {"pushed": False, "reason": "UNOBSERVED", "error": str(exc)}
    print(json.dumps(out, indent=2, sort_keys=True) if args.json else out)
    return 0 if out.get("pushed") or out.get("reason") == "unchanged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
