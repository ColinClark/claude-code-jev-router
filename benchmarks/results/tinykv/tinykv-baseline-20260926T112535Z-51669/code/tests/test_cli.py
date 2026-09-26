import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_cli(*args, cwd=REPO_ROOT):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def test_set_and_get(tmp_path):
    db = tmp_path / "db.json"
    result = run_cli("--db", str(db), "set", "name", '"colin"')
    assert result.returncode == 0

    result = run_cli("--db", str(db), "get", "name")
    assert result.returncode == 0
    assert json.loads(result.stdout) == "colin"


def test_set_plain_string_falls_back_when_not_json(tmp_path):
    db = tmp_path / "db.json"
    result = run_cli("--db", str(db), "set", "name", "colin")
    assert result.returncode == 0

    result = run_cli("--db", str(db), "get", "name")
    assert result.returncode == 0
    assert json.loads(result.stdout) == "colin"


def test_set_json_number(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "count", "42")
    result = run_cli("--db", str(db), "get", "count")
    assert json.loads(result.stdout) == 42


def test_get_missing_key_exits_1(tmp_path):
    db = tmp_path / "db.json"
    result = run_cli("--db", str(db), "get", "missing")
    assert result.returncode == 1


def test_get_expired_key_exits_1(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "temp", "1", "--ttl", "0")
    result = run_cli("--db", str(db), "get", "temp")
    assert result.returncode == 1


def test_delete(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "a", "1")
    result = run_cli("--db", str(db), "del", "a")
    assert result.returncode == 0

    result = run_cli("--db", str(db), "get", "a")
    assert result.returncode == 1


def test_keys(tmp_path):
    db = tmp_path / "db.json"
    run_cli("--db", str(db), "set", "a", "1")
    run_cli("--db", str(db), "set", "b", "2")
    result = run_cli("--db", str(db), "keys")
    assert result.returncode == 0
    assert sorted(result.stdout.split()) == ["a", "b"]
