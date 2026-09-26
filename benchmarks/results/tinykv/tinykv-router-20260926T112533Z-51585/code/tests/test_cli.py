"""End-to-end CLI tests via ``python -m tinykv`` subprocesses."""

import json
import subprocess
import sys
import time
from pathlib import Path

from tinykv.store import Store

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cli(db_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db_path), *args],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
        check=False,
    )


def test_set_then_get_json_value(db_path: Path) -> None:
    result = run_cli(db_path, "set", "cfg", '{"a": [1, 2], "b": true}')
    assert result.returncode == 0
    assert result.stdout == ""

    result = run_cli(db_path, "get", "cfg")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"a": [1, 2], "b": True}
    assert result.stdout == json.dumps({"a": [1, 2], "b": True}) + "\n"


def test_set_number_is_parsed_as_json(db_path: Path) -> None:
    assert run_cli(db_path, "set", "n", "42").returncode == 0
    result = run_cli(db_path, "get", "n")
    assert result.returncode == 0
    assert result.stdout == "42\n"
    assert Store(db_path).get("n") == 42


def test_set_non_json_is_stored_as_plain_string(db_path: Path) -> None:
    assert run_cli(db_path, "set", "greeting", "hello world").returncode == 0
    result = run_cli(db_path, "get", "greeting")
    assert result.returncode == 0
    assert result.stdout == '"hello world"\n'
    assert Store(db_path).get("greeting") == "hello world"


def test_get_missing_key_exits_1_with_no_output(db_path: Path) -> None:
    result = run_cli(db_path, "get", "nope")
    assert result.returncode == 1
    assert result.stdout == ""

    run_cli(db_path, "set", "other", "1")
    result = run_cli(db_path, "get", "nope")
    assert result.returncode == 1
    assert result.stdout == ""


def test_del_removes_key(db_path: Path) -> None:
    run_cli(db_path, "set", "k", "v")
    assert run_cli(db_path, "get", "k").returncode == 0

    result = run_cli(db_path, "del", "k")
    assert result.returncode == 0
    assert run_cli(db_path, "get", "k").returncode == 1


def test_del_missing_key_exits_0(db_path: Path) -> None:
    result = run_cli(db_path, "del", "never-set")
    assert result.returncode == 0


def test_keys_lists_one_per_line(db_path: Path) -> None:
    result = run_cli(db_path, "keys")
    assert result.returncode == 0
    assert result.stdout == ""

    for key in ("alpha", "beta", "gamma"):
        assert run_cli(db_path, "set", key, "1").returncode == 0
    result = run_cli(db_path, "keys")
    assert result.returncode == 0
    assert sorted(result.stdout.splitlines()) == ["alpha", "beta", "gamma"]
    assert result.stdout.endswith("\n")

    run_cli(db_path, "del", "beta")
    assert sorted(run_cli(db_path, "keys").stdout.splitlines()) == ["alpha", "gamma"]


def test_cli_data_visible_to_store_api(db_path: Path) -> None:
    Store(db_path).set("from-api", [1, 2, 3])
    result = run_cli(db_path, "get", "from-api")
    assert result.returncode == 0
    assert json.loads(result.stdout) == [1, 2, 3]


def test_ttl_flag_is_passed_through(db_path: Path) -> None:
    before = time.time()
    assert run_cli(db_path, "set", "k", "v", "--ttl", "3600").returncode == 0
    after = time.time()
    entry = json.loads(db_path.read_text(encoding="utf-8"))["k"]
    assert before + 3600 <= entry["expires_at"] <= after + 3600
    assert run_cli(db_path, "get", "k").returncode == 0


def test_set_without_ttl_never_expires(db_path: Path) -> None:
    assert run_cli(db_path, "set", "k", "v").returncode == 0
    entry = json.loads(db_path.read_text(encoding="utf-8"))["k"]
    assert entry["expires_at"] is None


def test_ttl_expiry_end_to_end(db_path: Path) -> None:
    # A zero-length ttl expires as soon as it is written (expires_at <= now), which
    # exercises the full expiry path through the CLI without any sleeping.
    assert run_cli(db_path, "set", "gone", "v", "--ttl", "0").returncode == 0
    result = run_cli(db_path, "get", "gone")
    assert result.returncode == 1
    assert result.stdout == ""
    assert run_cli(db_path, "keys").stdout == ""


def test_missing_db_argument_is_usage_error() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "tinykv", "keys"],
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert "--db" in result.stderr
