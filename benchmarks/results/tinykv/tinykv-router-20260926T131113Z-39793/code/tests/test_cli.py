import json
import subprocess
import sys
import time

import pytest


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "cli.db.json")


def run(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", db, *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_set_get_string(db):
    assert run(db, "set", "name", "alice").returncode == 0
    r = run(db, "get", "name")
    assert r.returncode == 0
    assert r.stdout == "alice\n"


def test_set_get_json_value(db):
    assert run(db, "set", "cfg", '{"a": [1, 2]}').returncode == 0
    assert run(db, "set", "n", "42").returncode == 0
    r = run(db, "get", "cfg")
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"a": [1, 2]}
    assert json.loads(run(db, "get", "n").stdout) == 42
    with open(db, encoding="utf-8") as f:
        assert json.load(f)["n"]["value"] == 42


def test_get_missing_exits_1(db):
    r = run(db, "get", "nope")
    assert r.returncode == 1
    assert r.stdout == ""


def test_get_expired_exits_1(db):
    assert run(db, "set", "tmp", "v", "--ttl", "60").returncode == 0
    assert run(db, "get", "tmp").returncode == 0
    # Rewrite the file so the entry's expiry is in the past (no sleeping).
    with open(db, encoding="utf-8") as f:
        data = json.load(f)
    data["tmp"]["expires_at"] = time.time() - 10
    with open(db, "w", encoding="utf-8") as f:
        json.dump(data, f)
    r = run(db, "get", "tmp")
    assert r.returncode == 1
    assert "tmp" not in run(db, "keys").stdout.split()


def test_del(db):
    run(db, "set", "k", "v")
    assert run(db, "del", "k").returncode == 0
    assert run(db, "get", "k").returncode == 1
    assert run(db, "del", "k").returncode == 1


def test_keys(db):
    assert run(db, "keys").stdout == ""
    run(db, "set", "a", "1")
    run(db, "set", "b", "2")
    r = run(db, "keys")
    assert r.returncode == 0
    assert sorted(r.stdout.splitlines()) == ["a", "b"]


def test_missing_command_is_usage_error(db):
    assert run(db).returncode == 2
