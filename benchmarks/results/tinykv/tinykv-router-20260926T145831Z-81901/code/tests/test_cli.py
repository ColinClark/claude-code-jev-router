import os
import subprocess
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def cli(tmp_path):
    db = str(tmp_path / "cli.json")
    env = {**os.environ, "PYTHONPATH": ROOT + os.pathsep + os.environ.get("PYTHONPATH", "")}

    def run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "tinykv", "--db", db, *args],
            capture_output=True,
            text=True,
            env=env,
        )

    return run


def test_set_get_keys_del(cli):
    assert cli("set", "name", "alice").returncode == 0
    assert cli("set", "n", "42").returncode == 0
    assert cli("set", "obj", '{"a": [1, 2]}').returncode == 0

    r = cli("get", "name")
    assert (r.returncode, r.stdout) == (0, '"alice"\n')
    assert cli("get", "n").stdout == "42\n"
    assert cli("get", "obj").stdout == '{"a": [1, 2]}\n'

    r = cli("keys")
    assert (r.returncode, r.stdout) == (0, "n\nname\nobj\n")

    assert cli("del", "name").returncode == 0
    assert cli("get", "name").returncode == 1
    assert cli("keys").stdout == "n\nobj\n"


def test_get_missing_exits_1(cli):
    r = cli("get", "missing")
    assert r.returncode == 1
    assert r.stdout == ""
    assert "missing" in r.stderr


def test_get_expired_exits_1(cli, tmp_path):
    # Write an entry whose expiry is already in the past, avoiding a real sleep.
    db = tmp_path / "cli.json"
    db.write_text('{"old": {"value": 1, "expires_at": 1.0}}')
    assert cli("get", "old").returncode == 1
    assert cli("keys").stdout == ""


def test_set_with_ttl(cli):
    assert cli("set", "k", "v", "--ttl", "3600").returncode == 0
    assert cli("get", "k").stdout == '"v"\n'
    assert cli("set", "k", "v", "--ttl", "0").returncode == 2


def test_usage_errors(cli):
    assert cli().returncode == 2
    assert cli("get").returncode == 2
