import json
import subprocess
import sys

import pytest


@pytest.fixture
def run(tmp_path):
    db = tmp_path / "cli.json"

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "tinykv", "--db", str(db), *args],
            capture_output=True,
            text=True,
        )

    _run.db = db
    return _run


def test_set_get_keys_del(run):
    assert run("set", "name", "alice").returncode == 0
    assert run("set", "n", "42").returncode == 0
    assert run("set", "obj", '{"a": [1, 2]}').returncode == 0

    r = run("get", "name")
    assert (r.returncode, r.stdout) == (0, '"alice"\n')
    assert json.loads(run("get", "n").stdout) == 42
    assert json.loads(run("get", "obj").stdout) == {"a": [1, 2]}

    assert run("keys").stdout.splitlines() == ["n", "name", "obj"]

    assert run("del", "name").returncode == 0
    assert run("get", "name").returncode == 1
    assert run("keys").stdout.splitlines() == ["n", "obj"]


def test_get_missing_exits_1(run):
    r = run("get", "missing")
    assert r.returncode == 1
    assert r.stdout == ""
    assert "missing" in r.stderr


def test_del_missing_exits_1(run):
    assert run("del", "missing").returncode == 1


def test_get_expired_exits_1(run):
    assert run("set", "k", "v", "--ttl", "60").returncode == 0
    assert run("get", "k").returncode == 0

    # Age the entry on disk instead of sleeping.
    data = json.loads(run.db.read_text())
    data["k"]["expires_at"] = 0
    run.db.write_text(json.dumps(data))

    assert run("get", "k").returncode == 1
    assert run("keys").stdout == ""


def test_invalid_ttl_rejected(run):
    r = run("set", "k", "v", "--ttl", "0")
    assert r.returncode == 2
    assert run("get", "k").returncode == 1
