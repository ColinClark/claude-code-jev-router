"""End-to-end tests for the tinykv CLI."""

from __future__ import annotations

import subprocess
import sys
import time

from tinykv.__main__ import main
from tinykv.store import Store


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tinykv", *args],
        capture_output=True,
        text=True,
    )


def test_set_get_string_value(tmp_path):
    db = tmp_path / "db.json"
    result = run_cli("--db", str(db), "set", "name", "alice")
    assert result.returncode == 0
    assert result.stdout == ""

    result = run_cli("--db", str(db), "get", "name")
    assert result.returncode == 0
    assert result.stdout == "alice\n"


def test_set_get_json_number(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "n", "42")

    result = run_cli("--db", str(db), "get", "n")
    assert result.returncode == 0
    assert result.stdout == "42\n"


def test_set_get_json_object(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "obj", '{"a": 1}')

    result = run_cli("--db", str(db), "get", "obj")
    assert result.returncode == 0
    assert result.stdout == '{"a": 1}\n'


def test_keys_output(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "b", "2")
    run_cli("--db", str(db), "set", "a", "1")

    result = run_cli("--db", str(db), "keys")
    assert result.returncode == 0
    assert result.stdout == "a\nb\n"


def test_del_existing_key(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "k", "v")

    result = run_cli("--db", str(db), "del", "k")
    assert result.returncode == 0

    result = run_cli("--db", str(db), "get", "k")
    assert result.returncode == 1


def test_del_missing_key(tmp_path):
    db = tmp_path / "db.json"
    result = run_cli("--db", str(db), "del", "nope")
    assert result.returncode == 1
    assert result.stdout == ""
    assert "nope" in result.stderr


def test_get_missing_key_exits_1(tmp_path):
    db = tmp_path / "db.json"
    result = run_cli("--db", str(db), "get", "nope")
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr != ""


def test_set_invalid_ttl_exits_2(tmp_path):
    db = tmp_path / "db.json"
    result = run_cli("--db", str(db), "set", "k", "v", "--ttl", "-1")
    assert result.returncode == 2
    assert result.stderr != ""


def test_expired_key_via_injected_clock(tmp_path):
    db = tmp_path / "db.json"
    Store(db, clock=lambda: time.time() - 100).set("k", "v", ttl=10)

    result = run_cli("--db", str(db), "get", "k")
    assert result.returncode == 1

    result = run_cli("--db", str(db), "keys")
    assert result.returncode == 0
    assert "k" not in result.stdout.splitlines()


def test_main_in_process(tmp_path, capsys):
    db = tmp_path / "db.json"
    assert main(["--db", str(db), "set", "x", "hello"]) == 0
    capsys.readouterr()

    assert main(["--db", str(db), "get", "x"]) == 0
    captured = capsys.readouterr()
    assert captured.out == "hello\n"

    assert main(["--db", str(db), "get", "missing"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err != ""
