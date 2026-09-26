"""End-to-end tests for the ``python -m tinykv`` command-line interface."""

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest


@pytest.fixture
def db(tmp_path: Path) -> Path:
    return tmp_path / "cli.db.json"


def run(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db), *args],
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
        cwd=db.parent,
    )


def test_set_get_keys_del_round_trip(db: Path) -> None:
    r = run(db, "set", "greeting", "hello")
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")

    r = run(db, "set", "count", "42")
    assert r.returncode == 0

    r = run(db, "get", "greeting")
    assert (r.returncode, r.stdout) == (0, "hello\n")

    r = run(db, "get", "count")
    assert (r.returncode, r.stdout) == (0, "42\n")

    r = run(db, "keys")
    assert r.returncode == 0
    assert sorted(r.stdout.splitlines()) == ["count", "greeting"]

    r = run(db, "del", "greeting")
    assert (r.returncode, r.stdout) == (0, "")

    r = run(db, "get", "greeting")
    assert r.returncode == 1

    r = run(db, "keys")
    assert (r.returncode, r.stdout) == (0, "count\n")


def test_get_missing_key_exits_1(db: Path) -> None:
    r = run(db, "get", "nope")
    assert r.returncode == 1
    assert r.stdout == ""
    assert "nope" in r.stderr


def test_del_missing_key_is_idempotent(db: Path) -> None:
    r = run(db, "del", "nope")
    assert (r.returncode, r.stdout) == (0, "")
    run(db, "set", "k", "v")
    assert run(db, "del", "k").returncode == 0
    assert run(db, "del", "k").returncode == 0


def test_keys_on_empty_store(db: Path) -> None:
    r = run(db, "keys")
    assert (r.returncode, r.stdout) == (0, "")


def test_get_expired_key_exits_1(db: Path) -> None:
    # Real (short) sleep: the CLI runs in a separate process, so the clock can't
    # be mocked. 0.1s ttl vs 0.3s sleep leaves a wide margin.
    r = run(db, "set", "tmp", "v", "--ttl", "0.1")
    assert r.returncode == 0
    time.sleep(0.3)
    r = run(db, "get", "tmp")
    assert r.returncode == 1
    assert r.stdout == ""
    assert run(db, "keys").stdout == ""


def test_get_with_unexpired_ttl(db: Path) -> None:
    assert run(db, "set", "k", "v", "--ttl", "3600").returncode == 0
    r = run(db, "get", "k")
    assert (r.returncode, r.stdout) == (0, "v\n")


def test_json_object_round_trip(db: Path) -> None:
    assert run(db, "set", "obj", '{"a": 1, "b": [true, null]}').returncode == 0
    r = run(db, "get", "obj")
    assert r.returncode == 0
    assert json.loads(r.stdout) == {"a": 1, "b": [True, None]}
    # Stored as a real JSON object on disk, not as a string.
    on_disk = json.loads(db.read_text(encoding="utf-8"))
    assert on_disk["obj"]["value"] == {"a": 1, "b": [True, None]}


@pytest.mark.parametrize(
    ("raw", "stored", "printed"),
    [
        ("[1, 2, 3]", [1, 2, 3], "[1, 2, 3]"),
        ("3.5", 3.5, "3.5"),
        ("true", True, "true"),
        ("null", None, "null"),
        ('"quoted"', "quoted", "quoted"),
        ("not json {", "not json {", "not json {"),
        ("hello world", "hello world", "hello world"),
    ],
)
def test_value_parsing(db: Path, raw: str, stored: object, printed: str) -> None:
    assert run(db, "set", "k", raw).returncode == 0
    assert json.loads(db.read_text(encoding="utf-8"))["k"]["value"] == stored
    r = run(db, "get", "k")
    assert (r.returncode, r.stdout) == (0, printed + "\n")
