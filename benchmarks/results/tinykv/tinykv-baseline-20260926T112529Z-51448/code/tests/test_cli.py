import json
import subprocess
import sys


def run_cli(db_path, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db_path), *args],
        capture_output=True,
        text=True,
    )


def test_cli_set_and_get(tmp_path):
    db_path = tmp_path / "db.json"
    result = run_cli(db_path, "set", "name", '"alice"')
    assert result.returncode == 0

    result = run_cli(db_path, "get", "name")
    assert result.returncode == 0
    assert json.loads(result.stdout) == "alice"


def test_cli_set_plain_string_value(tmp_path):
    db_path = tmp_path / "db.json"
    run_cli(db_path, "set", "name", "alice")
    result = run_cli(db_path, "get", "name")
    assert result.returncode == 0
    assert json.loads(result.stdout) == "alice"


def test_cli_set_json_value(tmp_path):
    db_path = tmp_path / "db.json"
    run_cli(db_path, "set", "data", '{"x": 1, "y": [1, 2, 3]}')
    result = run_cli(db_path, "get", "data")
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"x": 1, "y": [1, 2, 3]}


def test_cli_get_missing_key_exits_1(tmp_path):
    db_path = tmp_path / "db.json"
    result = run_cli(db_path, "get", "missing")
    assert result.returncode == 1


def test_cli_get_expired_key_exits_1(tmp_path):
    db_path = tmp_path / "db.json"
    run_cli(db_path, "set", "temp", '"x"', "--ttl", "0.01")
    import time

    time.sleep(0.05)
    result = run_cli(db_path, "get", "temp")
    assert result.returncode == 1


def test_cli_del(tmp_path):
    db_path = tmp_path / "db.json"
    run_cli(db_path, "set", "a", "1")
    result = run_cli(db_path, "del", "a")
    assert result.returncode == 0
    result = run_cli(db_path, "get", "a")
    assert result.returncode == 1


def test_cli_keys(tmp_path):
    db_path = tmp_path / "db.json"
    run_cli(db_path, "set", "a", "1")
    run_cli(db_path, "set", "b", "2")
    result = run_cli(db_path, "keys")
    assert result.returncode == 0
    assert sorted(result.stdout.split()) == ["a", "b"]
