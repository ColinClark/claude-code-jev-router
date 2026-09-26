import json
import subprocess
import sys

import pytest

from tinykv.cli import main
from tinykv.store import Store


def run_cli(*args):
    """Run the CLI in a real subprocess via ``python -m tinykv``."""
    return subprocess.run(
        [sys.executable, "-m", "tinykv", *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_set_get_del_keys_roundtrip(db_path):
    db = str(db_path)
    assert run_cli("--db", db, "set", "name", "alice").returncode == 0
    assert run_cli("--db", db, "set", "count", "42").returncode == 0
    assert run_cli("--db", db, "set", "obj", '{"a": [1, 2]}').returncode == 0

    got = run_cli("--db", db, "get", "name")
    assert got.returncode == 0 and got.stdout == "alice\n"
    got = run_cli("--db", db, "get", "count")
    assert got.returncode == 0 and got.stdout == "42\n"
    got = run_cli("--db", db, "get", "obj")
    assert got.returncode == 0 and json.loads(got.stdout) == {"a": [1, 2]}

    keys = run_cli("--db", db, "keys")
    assert keys.returncode == 0
    assert keys.stdout.splitlines() == ["name", "count", "obj"]

    assert run_cli("--db", db, "del", "name").returncode == 0
    assert run_cli("--db", db, "get", "name").returncode == 1
    assert run_cli("--db", db, "keys").stdout.splitlines() == ["count", "obj"]


def test_values_are_json_typed(db_path):
    db = str(db_path)
    run_cli("--db", db, "set", "n", "42")
    run_cli("--db", db, "set", "s", "hello world")
    store = Store(db_path)
    assert store.get("n") == 42
    assert store.get("s") == "hello world"


def test_get_missing_key_exits_1(db_path):
    result = run_cli("--db", str(db_path), "get", "nothing")
    assert result.returncode == 1
    assert result.stdout == ""


def test_get_expired_key_exits_1(db_path):
    # Write an entry whose expiry (t=1 on a clock frozen at 0) is already in the
    # past for the real clock the CLI subprocess uses, so no sleeping is needed.
    Store(db_path, clock=lambda: 0.0).set("gone", "x", ttl=1)
    assert run_cli("--db", str(db_path), "get", "gone").returncode == 1
    assert run_cli("--db", str(db_path), "keys").stdout == ""


def test_set_with_ttl(db_path):
    db = str(db_path)
    assert run_cli("--db", db, "set", "tmp", "v", "--ttl", "3600").returncode == 0
    entry = json.loads(db_path.read_text())["tmp"]
    assert entry["value"] == "v"
    assert entry["expires"] is not None


def test_set_with_bad_ttl_fails(db_path):
    result = run_cli("--db", str(db_path), "set", "tmp", "v", "--ttl", "0")
    assert result.returncode == 2
    assert "ttl" in result.stderr


def test_main_in_process(db_path, capsys):
    db = str(db_path)
    assert main(["--db", db, "set", "k", "v"]) == 0
    assert main(["--db", db, "get", "k"]) == 0
    assert capsys.readouterr().out == "v\n"
    assert main(["--db", db, "get", "missing"]) == 1
    assert main(["--db", db, "del", "k"]) == 0
    assert main(["--db", db, "keys"]) == 0
    assert capsys.readouterr().out == ""


def test_missing_db_flag_is_usage_error():
    with pytest.raises(SystemExit) as exc:
        main(["get", "k"])
    assert exc.value.code == 2
