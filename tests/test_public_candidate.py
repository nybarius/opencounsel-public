"""RED: the fresh public history, built by regrow, never by publishing the private history.

`scripts/build_public_candidate.py` runs the privilege audit on the tree; unless the verdict is
CLEAN, or REVIEW with every item operator-confirmed in the manifest, it refuses. It then writes the
current tree as one orphan commit (no parent, no private history) on `refs/heads/public/candidate`
and pushes it, never force: a second run with an unchanged tree pushes nothing; a changed tree
pushes a child of the remote tip.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_public_candidate.py"


def _git(cwd: Path, *args: str) -> str:
    env = dict(
        os.environ,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    return subprocess.run(
        ["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, env=env
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "docs").mkdir()
    (repo / "docs" / "LEGAL_FIXTURES.json").write_text(json.dumps({"fixtures": []}))
    (repo / "README.md").write_text("# clean\n")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "privilege_audit.py").write_bytes(
        (ROOT / "scripts" / "privilege_audit.py").read_bytes()
    )
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "private history 1")
    (repo / "README.md").write_text("# clean, second commit\n")
    _git(repo, "commit", "-qam", "private history 2")
    origin = tmp_path / "origin.git"
    _git(tmp_path, "init", "-q", "--bare", "-b", "main", str(origin))
    _git(repo, "remote", "add", "origin", str(origin))
    return repo, origin


def _run(repo: Path, *args: str, env: dict[str, str] | None = None) -> dict:
    done = subprocess.run(
        ["python3", str(SCRIPT), "--root", str(repo), "--json", *args],
        capture_output=True,
        text=True,
        env=env,
    )
    return json.loads(done.stdout)


def test_a_clean_tree_becomes_one_orphan_commit_on_the_candidate_branch(tmp_path: Path) -> None:
    repo, origin = _repo(tmp_path)
    out = _run(repo, "--ref", "public/candidate")
    assert out["pushed"] and out["audit"] == "CLEAN" and out["parent"] is None
    assert _git(origin, "rev-parse", "refs/heads/public/candidate") == out["commit"]
    assert _git(origin, "rev-list", "--count", "refs/heads/public/candidate") == "1"
    names = _git(origin, "ls-tree", "--name-only", "-r", "refs/heads/public/candidate").split()
    assert "README.md" in names and "docs/LEGAL_FIXTURES.json" in names
    assert _git(origin, "show", "refs/heads/public/candidate:README.md") == "# clean, second commit"
    again = _run(repo, "--ref", "public/candidate")
    assert not again["pushed"] and again["reason"] == "unchanged"
    (repo / "README.md").write_text("# clean, third\n")
    third = _run(repo, "--ref", "public/candidate")
    assert third["pushed"] and third["parent"] == out["commit"]
    assert _git(origin, "rev-list", "--count", "refs/heads/public/candidate") == "2"


def test_a_refused_audit_pushes_nothing(tmp_path: Path) -> None:
    repo, origin = _repo(tmp_path)
    (repo / "notes.md").write_text("ATTORNEY-CLIENT PRIVILEGED\n")
    out = _run(repo, "--ref", "public/candidate")
    assert not out["pushed"] and out["reason"] == "audit:REFUSED"
    assert _git(origin, "for-each-ref", "--format=%(refname)", "refs/heads/") == ""


def test_a_review_item_not_confirmed_refuses_and_a_confirmed_one_passes(tmp_path: Path) -> None:
    repo, _ = _repo(tmp_path)
    (repo / "cite.md").write_text("See Smith v. Jones Holdings, Inc.\n")
    out = _run(repo, "--ref", "public/candidate")
    assert not out["pushed"] and out["reason"] == "audit:REVIEW" and out["review"]
    (repo / "docs" / "LEGAL_FIXTURES.json").write_text(
        json.dumps({"fixtures": [], "public_captions": ["Smith v. Jones Holdings, Inc."]})
    )
    out = _run(repo, "--ref", "public/candidate")
    assert out["pushed"] and out["audit"] == "CLEAN"

def test_candidate_builder_supplies_its_own_commit_identity(tmp_path: Path) -> None:
    repo, origin = _repo(tmp_path)
    home = tmp_path / "empty-home"
    home.mkdir()
    env = dict(os.environ, HOME=str(home))
    for key in (
        "GIT_AUTHOR_NAME",
        "GIT_AUTHOR_EMAIL",
        "GIT_COMMITTER_NAME",
        "GIT_COMMITTER_EMAIL",
    ):
        env.pop(key, None)

    out = _run(repo, "--ref", "public/candidate", env=env)

    assert out["pushed"], out
    identity = _git(
        origin,
        "show",
        "-s",
        "--format=%an <%ae>%n%cn <%ce>",
        "refs/heads/public/candidate",
    )
    assert identity == (
        "OpenCounsel candidate builder <candidate@opencounsel.local>\n"
        "OpenCounsel candidate builder <candidate@opencounsel.local>"
    )
