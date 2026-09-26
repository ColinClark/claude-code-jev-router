import json
import subprocess
import sys
from pathlib import Path

import pytest

from tinykv import Store

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def db(tmp_path):
    return tmp_path / "cli.db.json"


def run(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db), *args],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )


def test_set_get_roundtrip(db):
    assert run(db, "set", "name", "alice").returncode == 0
    r = run(db, "get", "name")
    assert r.returncode == 0
    assert r.stdout == "alice\n"


def test_json_values(db):
    run(db, "set", "n", "42")
    run(db, "set", "obj", '{"a": [1, 2]}')
    assert Store(db).get("n") == 42
    assert Store(db).get("obj") == {"a": [1, 2]}
    assert json.loads(run(db, "get", "obj").stdout) == {"a": [1, 2]}


def test_get_missing_exits_1(db):
    r = run(db, "get", "missing")
    assert r.returncode == 1
    assert r.stdout == ""
    assert "missing" in r.stderr


def test_get_expired_exits_1(db):
    Store(db, clock=lambda: 0.0).set("old", "v", ttl=1)  # expired long ago
    assert run(db, "get", "old").returncode == 1
    assert run(db, "keys").stdout == ""


def test_set_with_ttl(db):
    assert run(db, "set", "t", "v", "--ttl", "3600").returncode == 0
    assert run(db, "get", "t").stdout == "v\n"
    raw = json.loads(db.read_text())
    assert raw["t"]["e"] is not None


def test_invalid_ttl_rejected(db):
    r = run(db, "set", "t", "v", "--ttl", "0")
    assert r.returncode == 2
    assert not db.exists()


def test_del_and_keys(db):
    run(db, "set", "b", "1")
    run(db, "set", "a", "2")
    assert run(db, "keys").stdout == "a\nb\n"
    assert run(db, "del", "a").returncode == 0
    assert run(db, "keys").stdout == "b\n"
    assert run(db, "get", "a").returncode == 1


def test_usage_error(db):
    assert run(db).returncode == 2
