import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def cli(tmp_path):
    db = tmp_path / "db.json"

    def run(*args):
        return subprocess.run(
            [sys.executable, "-m", "tinykv", "--db", str(db), *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    return run


def test_set_then_get(cli):
    assert cli("set", "name", "alice").returncode == 0
    result = cli("get", "name")
    assert result.returncode == 0
    assert json.loads(result.stdout) == "alice"


def test_set_parses_json_value(cli):
    assert cli("set", "cfg", '{"a": [1, 2]}').returncode == 0
    assert json.loads(cli("get", "cfg").stdout) == {"a": [1, 2]}
    assert cli("set", "n", "42").returncode == 0
    assert json.loads(cli("get", "n").stdout) == 42


def test_get_missing_exits_1(cli):
    result = cli("get", "missing")
    assert result.returncode == 1
    assert result.stdout == ""


def test_del_then_get_exits_1(cli):
    cli("set", "k", "v")
    assert cli("del", "k").returncode == 0
    result = cli("get", "k")
    assert result.returncode == 1
    assert result.stdout == ""


def test_del_missing_exits_0(cli):
    assert cli("del", "nope").returncode == 0


def test_keys_lists_set_keys(cli):
    for key in ("a", "b", "c"):
        cli("set", key, "1")
    cli("del", "b")
    result = cli("keys")
    assert result.returncode == 0
    assert sorted(result.stdout.splitlines()) == ["a", "c"]


def test_ttl_expiry(cli):
    assert cli("set", "k", "v", "--ttl", "0.05").returncode == 0
    time.sleep(0.1)
    result = cli("get", "k")
    assert result.returncode == 1
    assert result.stdout == ""
    assert cli("keys").stdout == ""
