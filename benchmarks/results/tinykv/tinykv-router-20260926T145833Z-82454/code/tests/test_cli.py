import json
import subprocess
import sys

import pytest

from tinykv.store import Store


@pytest.fixture
def db(tmp_path):
    return tmp_path / "db.json"


def run(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_set_get_roundtrip(db):
    assert run(db, "set", "name", "alice").returncode == 0
    result = run(db, "get", "name")
    assert result.returncode == 0
    assert result.stdout == "alice\n"


def test_json_values(db):
    run(db, "set", "n", "42")
    run(db, "set", "obj", '{"a": [1, 2]}')
    assert Store(db).get("n") == 42
    assert Store(db).get("obj") == {"a": [1, 2]}
    assert json.loads(run(db, "get", "obj").stdout) == {"a": [1, 2]}


def test_get_missing_exits_1(db):
    result = run(db, "get", "nope")
    assert result.returncode == 1
    assert result.stdout == ""


def test_get_expired_exits_1(db):
    # Write an already-expired entry directly so no sleep is needed.
    Store(db, clock=lambda: 0.0).set("old", "v", ttl=1)
    assert run(db, "get", "old").returncode == 1


def test_set_with_ttl(db):
    assert run(db, "set", "k", "v", "--ttl", "3600").returncode == 0
    entry = json.loads(db.read_text())["k"]
    assert entry["v"] == "v"
    assert entry["e"] is not None
    assert run(db, "get", "k").stdout == "v\n"


def test_invalid_ttl(db):
    assert run(db, "set", "k", "v", "--ttl", "0").returncode == 2


def test_del_and_keys(db):
    run(db, "set", "b", "2")
    run(db, "set", "a", "1")
    assert run(db, "keys").stdout == "a\nb\n"
    assert run(db, "del", "a").returncode == 0
    assert run(db, "del", "a").returncode == 1
    assert run(db, "keys").stdout == "b\n"
    assert run(db, "get", "a").returncode == 1
