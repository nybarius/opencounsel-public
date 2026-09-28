"""RED: the privilege gate -- a deterministic scanner over every file, fixture, doc and history blob
that would ship, before anything is marked publish-ready.

It refuses attorney-client privileged or work-product markers, real client or matter names outside
the manifest of public legal fixtures, non-public case facts under seal, PII, secrets and
credentials, private URLs and internal hostnames. Anything uncertain is listed for the operator's
review and never shipped on a guess. The retained legal fixtures are named in
`docs/LEGAL_FIXTURES.json` with their public source; the history scan reads every blob reachable
from the branch, so a fresh public history is planned from the spore regrow, never the private
history.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "privilege_audit.py"


def _run(*args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["python3", str(SCRIPT), *args], capture_output=True, text=True, cwd=cwd)


def _repo(tmp_path: Path, files: dict[str, str]) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    for rel, text in files.items():
        (repo / rel).parent.mkdir(parents=True, exist_ok=True)
        (repo / rel).write_text(text)
    env = {
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@t",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@t",
    }
    import os

    e = dict(os.environ, **env)
    subprocess.run(["git", "-C", str(repo), "init", "-q", "-b", "main"], check=True, env=e)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=e)
    subprocess.run(["git", "-C", str(repo), "commit", "-q", "-m", "a"], check=True, env=e)
    return repo


def test_a_clean_tree_with_a_manifested_public_fixture_passes(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        {
            "docs/LEGAL_FIXTURES.json": json.dumps(
                {
                    "fixtures": [
                        {
                            "path": "fixtures/dkt52.txt",
                            "public_source": "S.D.N.Y. 1:23-cv-11195, Dkt. 52 (Feb. 26, 2024), "
                            "via CourtListener/RECAP",
                            "captions": ["The New York Times Company v. Microsoft Corporation"],
                        }
                    ]
                }
            ),
            "fixtures/dkt52.txt": "The New York Times Company v. Microsoft Corporation, "
            "Dkt. 52 derivative\n",
            "README.md": "# demo\nContact: support@example.com\n",
        },
    )
    done = _run("--root", str(repo), "--json")
    out = json.loads(done.stdout)
    assert done.returncode == 0 and out["verdict"] == "CLEAN"
    assert out["scanned"]["tree_files"] >= 3 and out["scanned"]["history_blobs"] >= 3
    assert out["findings"] == [] and out["review"] == []


def test_privilege_markers_pii_secrets_and_private_hosts_are_refused(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        {
            "docs/LEGAL_FIXTURES.json": json.dumps({"fixtures": []}),
            "notes/memo.md": "ATTORNEY-CLIENT PRIVILEGED memo about the Acme matter\n",
            "notes/sealed.md": "Filed under seal: the settlement figure\n",
            "conf/keys.env": "OPENAI_API_KEY=sk-abcdefghijklmnopqrstuvwxyz1234\n",
            "conf/hosts.txt": "https://vault.internal.nexuspl.local/x and 10.0.0.12\n",
            "people.csv": "John Q. Public,123-45-6789,jqp@gmail.com\n",
        },
    )
    done = _run("--root", str(repo), "--json")
    out = json.loads(done.stdout)
    assert done.returncode == 1 and out["verdict"] == "REFUSED"
    kinds = {f["kind"] for f in out["findings"]}
    assert {"privilege", "seal", "secret", "private_host", "pii"} <= kinds
    paths = {f["path"] for f in out["findings"]}
    assert "notes/memo.md" in paths and "conf/keys.env" in paths and "people.csv" in paths


def test_an_unmanifested_caption_is_listed_for_review_not_shipped(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        {
            "docs/LEGAL_FIXTURES.json": json.dumps({"fixtures": []}),
            "fixtures/other.txt": "Smith v. Jones Holdings, Inc., motion to dismiss\n",
        },
    )
    done = _run("--root", str(repo), "--json")
    out = json.loads(done.stdout)
    assert done.returncode == 2 and out["verdict"] == "REVIEW"
    assert (
        out["review"][0]["path"] == "fixtures/other.txt"
        and "Smith v. Jones" in out["review"][0]["witness"]
    )


def test_history_blobs_are_scanned_even_when_the_tree_is_clean(tmp_path: Path) -> None:
    repo = _repo(
        tmp_path,
        {
            "docs/LEGAL_FIXTURES.json": json.dumps({"fixtures": []}),
            "a.txt": "work product of counsel\n",
        },
    )
    import os

    e = dict(
        os.environ,
        GIT_AUTHOR_NAME="t",
        GIT_AUTHOR_EMAIL="t@t",
        GIT_COMMITTER_NAME="t",
        GIT_COMMITTER_EMAIL="t@t",
    )
    (repo / "a.txt").write_text("clean now\n")
    subprocess.run(["git", "-C", str(repo), "commit", "-qam", "clean"], check=True, env=e)
    out = json.loads(_run("--root", str(repo), "--json").stdout)
    assert out["verdict"] == "REFUSED"
    assert any(f["where"] == "history" and f["kind"] == "privilege" for f in out["findings"])
    tree_only = json.loads(_run("--root", str(repo), "--json", "--no-history").stdout)
    assert tree_only["verdict"] == "CLEAN"


def test_this_repository_audits_clean_or_lists_its_review_items() -> None:
    """The gate on this tree: no finding may be a refusal; review items are the operator's list."""
    done = _run("--root", str(ROOT), "--json")
    out = json.loads(done.stdout)
    assert out["verdict"] in ("CLEAN", "REVIEW"), [f for f in out["findings"]][:10]
    manifest = json.loads((ROOT / "docs" / "LEGAL_FIXTURES.json").read_text())
    assert manifest["fixtures"] and all(f["public_source"] for f in manifest["fixtures"])
