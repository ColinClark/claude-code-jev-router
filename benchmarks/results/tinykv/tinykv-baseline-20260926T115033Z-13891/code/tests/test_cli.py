from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ROOT

from tinykv.cli import main
from tinykv.store import Store


def run(db: Path, *args: str) -> tuple[int, str, str]:
    """Run the CLI as a real subprocess via ``python -m tinykv``."""
    proc = subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_set_get_del_keys_via_subprocess(db_path: Path) -> None:
    assert run(db_path, "set", "name", "alice")[0] == 0
    assert run(db_path, "set", "count", "42")[0] == 0
    assert run(db_path, "set", "obj", '{"a": [1, 2]}')[0] == 0

    code, out, _ = run(db_path, "get", "name")
    assert (code, out) == (0, "alice\n")
    code, out, _ = run(db_path, "get", "count")
    assert (code, out) == (0, "42\n")
    code, out, _ = run(db_path, "get", "obj")
    assert code == 0 and json.loads(out) == {"a": [1, 2]}

    code, out, _ = run(db_path, "keys")
    assert (code, out) == (0, "count\nname\nobj\n")

    assert run(db_path, "del", "name")[0] == 0
    code, out, err = run(db_path, "get", "name")
    assert code == 1 and out == "" and "name" in err
    assert run(db_path, "keys")[1] == "count\nobj\n"


def test_get_missing_key_exits_1(db_path: Path) -> None:
    code, out, err = run(db_path, "get", "ghost")
    assert code == 1
    assert out == ""
    assert "ghost" in err


def test_get_expired_key_exits_1(db_path: Path) -> None:
    # Write a record whose deadline is long past, so no sleeping is needed.
    db_path.write_text(json.dumps({"old": {"value": "x", "expires": 1.0}}))
    code, out, _ = run(db_path, "get", "old")
    assert (code, out) == (1, "")
    assert run(db_path, "keys")[1] == ""


def test_set_with_ttl_records_deadline(db_path: Path) -> None:
    assert run(db_path, "set", "tmp", "v", "--ttl", "60")[0] == 0
    record = json.loads(db_path.read_text())["tmp"]
    assert record["value"] == "v"
    assert record["expires"] is not None
    assert Store(db_path).get("tmp") == "v"


def test_invalid_ttl_is_a_usage_error(db_path: Path) -> None:
    code, _, err = run(db_path, "set", "k", "v", "--ttl", "0")
    assert code == 2
    assert "ttl must be positive" in err
    code, _, err = run(db_path, "set", "k", "v", "--ttl", "soon")
    assert code == 2


def test_missing_db_flag_is_a_usage_error() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "tinykv", "keys"], cwd=ROOT, capture_output=True, text=True
    )
    assert proc.returncode == 2
    assert "--db" in proc.stderr


def test_main_in_process(db_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db = str(db_path)
    assert main(["--db", db, "set", "k", "true"]) == 0
    assert main(["--db", db, "get", "k"]) == 0
    assert capsys.readouterr().out == "true\n"
    assert main(["--db", db, "del", "k"]) == 0
    assert main(["--db", db, "get", "k"]) == 1
    assert main(["--db", db, "keys"]) == 0
    assert capsys.readouterr().out == ""


def test_non_json_value_is_stored_as_string(db_path: Path) -> None:
    assert main(["--db", str(db_path), "set", "k", "not json {"]) == 0
    assert Store(db_path).get("k") == "not json {"
