"""Publication preparation preserves exact audit scope, operator review and private ancestry."""

from __future__ import annotations

import hashlib
import json

from test_public_candidate import _git, _repo, _run


def test_candidate_builder_preserves_the_private_head_and_index(tmp_path):
    repo, origin = _repo(tmp_path)
    head = _git(repo, "rev-parse", "HEAD")
    index = (repo / ".git" / "index").read_bytes()
    (repo / "README.md").write_text("# reviewed working tree\n")
    (repo / "untracked.txt").write_text("synthetic untracked content\n")
    out = _run(repo)
    assert out["pushed"], out
    assert _git(repo, "rev-parse", "HEAD") == head
    assert (repo / ".git" / "index").read_bytes() == index
    assert _git(origin, "show", "public/candidate:untracked.txt") == "synthetic untracked content"
    assert _git(origin, "cat-file", "-p", out["commit"]).count("\nparent ") == 0


def test_exact_operator_confirmation_cannot_authorize_changed_bytes(tmp_path):
    repo, _ = _repo(tmp_path)
    path = repo / "case.md"
    path.write_text("Example v. Synthetic\n")
    review = _run(repo)["review"][0]
    manifest = {
        "fixtures": [],
        "operator_confirmed_reviews": [
            {
                **review,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "confirmed_by": "operator",
                "confirmed_at": "2026-09-27",
            }
        ],
    }
    (repo / "docs" / "LEGAL_FIXTURES.json").write_text(json.dumps(manifest))
    out = _run(repo)
    assert out["pushed"] and out["audit"] == "REVIEW", out
    path.write_text("Example v. Synthetic\nchanged content\n")
    stale = _run(repo)
    assert not stale["pushed"] and stale["reason"] == "audit:REVIEW"


def test_unobserved_remote_and_private_tip_are_not_treated_as_fresh_history(tmp_path):
    repo, origin = _repo(tmp_path)
    _git(repo, "remote", "set-url", "origin", str(tmp_path / "missing.git"))
    assert _run(repo)["reason"] == "UNOBSERVED"
    _git(repo, "remote", "set-url", "origin", str(origin))
    _git(repo, "push", "origin", "HEAD:refs/heads/public/candidate")
    tip = _git(origin, "rev-parse", "public/candidate")
    assert not _run(repo)["pushed"]
    assert _git(origin, "rev-parse", "public/candidate") == tip


def test_symlinks_and_non_candidate_refs_are_refused(tmp_path):
    repo, origin = _repo(tmp_path)
    (repo / "link").symlink_to(repo / "README.md")
    assert not _run(repo)["pushed"]
    (repo / "link").unlink()
    assert not _run(repo, "--ref", "main")["pushed"]
    assert _git(origin, "for-each-ref", "refs/heads/") == ""
