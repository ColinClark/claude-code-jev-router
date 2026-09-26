"""Tests for the tinykv command-line interface."""

from __future__ import annotations

import json
import subprocess
import sys

import pytest

from tinykv.__main__ import main
from tinykv.store import Store


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "store.json")


def test_set_get_string_roundtrip(db_path, capsys):
    assert main(["--db", db_path, "set", "name", "alice"]) == 0
    capsys.readouterr()
    assert main(["--db", db_path, "get", "name"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == json.dumps("alice")


def test_set_get_number_roundtrip(db_path, capsys):
    assert main(["--db", db_path, "set", "n", "42"]) == 0
    capsys.readouterr()
    assert main(["--db", db_path, "get", "n"]) == 0
    out = capsys.readouterr().out
    assert out.strip() == "42"


def test_set_get_json_object_roundtrip(db_path, capsys):
    assert main(["--db", db_path, "set", "obj", '{"a": 1}']) == 0
    capsys.readouterr()
    assert main(["--db", db_path, "get", "obj"]) == 0
    out = capsys.readouterr().out
    assert json.loads(out) == {"a": 1}


def test_get_missing_key(db_path, capsys):
    rc = main(["--db", db_path, "get", "nope"])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert captured.err.strip() != ""


def test_del_existing_then_get_missing(db_path, capsys):
    assert main(["--db", db_path, "set", "k", "v"]) == 0
    capsys.readouterr()
    assert main(["--db", db_path, "del", "k"]) == 0
    capsys.readouterr()
    rc = main(["--db", db_path, "get", "k"])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""


def test_del_missing_key(db_path, capsys):
    rc = main(["--db", db_path, "del", "nope"])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.err.strip() != ""


def test_keys_listing(db_path, capsys):
    main(["--db", db_path, "set", "b", "2"])
    main(["--db", db_path, "set", "a", "1"])
    capsys.readouterr()
    rc = main(["--db", db_path, "keys"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.splitlines() == ["a", "b"]


def test_stored_null_is_found_by_get(db_path, capsys):
    assert main(["--db", db_path, "set", "empty", "null"]) == 0
    capsys.readouterr()
    rc = main(["--db", db_path, "get", "empty"])
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "null"


def test_invalid_ttl_exits_2(db_path, capsys):
    rc = main(["--db", db_path, "set", "k", "v", "--ttl", "-1"])
    captured = capsys.readouterr()
    assert rc == 2
    assert captured.err.strip() != ""


def test_ttl_expiry_via_separate_clock(db_path, capsys):
    # Set a key with a short ttl via the CLI, then read it back through a
    # Store constructed with a clock that reports a far-future time, so we
    # never need a real sleep.
    assert main(["--db", db_path, "set", "temp", "1", "--ttl", "1"]) == 0
    capsys.readouterr()

    far_future_store = Store(db_path, clock=lambda: 10_000_000_000.0)
    sentinel = object()
    assert far_future_store.get("temp", default=sentinel) is sentinel


def test_get_expired_key_exits_1(db_path, capsys):
    # Seed an entry whose expiry is already in the past; no sleep needed.
    Store(db_path, clock=lambda: 0.0).set("old", "v", ttl=1)
    rc = main(["--db", db_path, "get", "old"])
    captured = capsys.readouterr()
    assert rc == 1
    assert captured.out == ""
    assert main(["--db", db_path, "keys"]) == 0
    assert capsys.readouterr().out == ""


def test_subprocess_set_get_roundtrip(tmp_path):
    db = str(tmp_path / "sub.json")

    set_result = subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", db, "set", "greeting", "hello"],
        capture_output=True,
        text=True,
    )
    assert set_result.returncode == 0

    get_result = subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", db, "get", "greeting"],
        capture_output=True,
        text=True,
    )
    assert get_result.returncode == 0
    assert get_result.stdout.strip() == json.dumps("hello")


def test_subprocess_get_missing_exits_1(tmp_path):
    db = str(tmp_path / "sub_missing.json")

    get_result = subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", db, "get", "nope"],
        capture_output=True,
        text=True,
    )
    assert get_result.returncode == 1
    assert get_result.stdout == ""
