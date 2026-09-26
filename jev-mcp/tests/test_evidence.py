import subprocess

import pytest

from jev_router import evidence as ev


@pytest.fixture
def repo(tmp_path):
    def git(*args):
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    git("add", ".")
    git("commit", "-qm", "init")
    return tmp_path


def test_fingerprint_changes_on_unstaged_staged_and_untracked(repo):
    base = ev.fingerprint(repo)
    (repo / "src" / "a.py").write_text("x = 2\n")
    unstaged = ev.fingerprint(repo)
    assert unstaged != base
    subprocess.run(["git", "-C", str(repo), "add", "src/a.py"], check=True)
    staged = ev.fingerprint(repo)
    assert staged != unstaged  # moving a change into the index is a different workspace state
    (repo / "new.txt").write_text("a")
    with_untracked = ev.fingerprint(repo)
    assert with_untracked != staged
    (repo / "new.txt").write_text("b")
    assert ev.fingerprint(repo) != with_untracked


def test_collect_reports_pass_fail_and_scope(repo):
    (repo / "src" / "a.py").write_text("x = 2\n")
    (repo / "docs.md").write_text("d")
    packet = ev.collect(repo, [("ok", "true"), ("bad", "exit 3")], allow=["src/*"], na=["lint"], timeout=30)
    e = packet["evidence"]
    assert [(c["name"], c["status"], c["exit_code"]) for c in e["checks"]] == [
        ("ok", "PASS", 0),
        ("bad", "FAIL", 3),
        ("lint", "NOT_APPLICABLE", None),
    ]
    assert e["scope_ok"] is False and packet["out_of_scope"] == ["docs.md"]
    assert packet["stale"] is False and e["fingerprint"] == ev.fingerprint(repo)
    assert e["known_failures"] == ["bad failed (exit 3)"]


def test_collect_detects_checks_that_mutate_workspace(repo):
    packet = ev.collect(repo, [("fmt", "echo y >> src/a.py")], allow=[], na=[], timeout=30)
    assert packet["stale"] is True and packet["evidence"]["scope_ok"] is None


def test_collect_timeout_is_error(repo):
    packet = ev.collect(repo, [("slow", "sleep 5")], allow=[], na=[], timeout=0.2)
    assert packet["evidence"]["checks"][0] == {"name": "slow", "status": "ERROR", "exit_code": None}


def test_verify_cli(repo, capsys):
    fp = ev.fingerprint(repo)
    assert ev.main(["--repo", str(repo), "verify", fp]) == 0
    (repo / "z").write_text("z")
    assert ev.main(["--repo", str(repo), "verify", fp]) == 1
