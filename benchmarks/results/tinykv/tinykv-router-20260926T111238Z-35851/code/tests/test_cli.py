import json
import subprocess
import sys
import time

import pytest

from tinykv.__main__ import main


def run(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db), *args],
        capture_output=True,
        text=True,
    )


@pytest.fixture
def db(tmp_path):
    return tmp_path / "db.json"


def test_set_get_string(db):
    assert run(db, "set", "name", "alice").returncode == 0
    r = run(db, "get", "name")
    assert r.returncode == 0
    assert r.stdout == "alice\n"


def test_set_get_json(db):
    assert run(db, "set", "n", "42").returncode == 0
    assert run(db, "get", "n").stdout == "42\n"
    assert run(db, "set", "obj", '{"a": [1, 2]}').returncode == 0
    r = run(db, "get", "obj")
    assert json.loads(r.stdout) == {"a": [1, 2]}


def test_get_missing(db):
    r = run(db, "get", "nope")
    assert r.returncode == 1
    assert r.stdout == ""


def test_del(db):
    run(db, "set", "k", "v")
    assert run(db, "del", "k").returncode == 0
    assert run(db, "del", "k").returncode == 1


def test_keys(db):
    run(db, "set", "b", "1")
    run(db, "set", "a", "2")
    r = run(db, "keys")
    assert r.returncode == 0
    assert r.stdout.splitlines() == ["a", "b"]


@pytest.mark.parametrize("ttl", ["0", "-1"])
def test_invalid_ttl(db, ttl):
    r = run(db, "set", "k", "v", "--ttl", ttl)
    assert r.returncode != 0
    assert r.stderr


def test_expiry_via_subprocess(db):
    assert run(db, "set", "k", "v", "--ttl", "0.2").returncode == 0
    time.sleep(0.3)
    r = run(db, "get", "k")
    assert r.returncode == 1
    assert r.stdout == ""


def test_expired_entry_on_disk(db, capsys):
    db.write_text(
        json.dumps({"version": 1, "data": {"k": {"value": "v", "expires_at": 1.0}}})
    )
    assert main(["--db", str(db), "get", "k"]) == 1
    assert capsys.readouterr().out == ""
