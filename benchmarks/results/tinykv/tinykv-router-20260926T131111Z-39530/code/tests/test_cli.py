import json
import subprocess
import sys


def run(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db), *args],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_set_get_del_keys(tmp_path):
    db = tmp_path / "cli.json"
    assert run(db, "set", "name", "alice").returncode == 0
    assert run(db, "set", "obj", '{"a": [1, 2]}').returncode == 0
    assert run(db, "set", "num", "42").returncode == 0

    r = run(db, "get", "name")
    assert (r.returncode, r.stdout) == (0, "alice\n")
    r = run(db, "get", "obj")
    assert r.returncode == 0 and json.loads(r.stdout) == {"a": [1, 2]}
    assert run(db, "get", "num").stdout == "42\n"

    r = run(db, "keys")
    assert (r.returncode, r.stdout) == (0, "name\nnum\nobj\n")

    assert run(db, "del", "name").returncode == 0
    assert run(db, "del", "name").returncode == 1
    assert run(db, "get", "name").returncode == 1
    assert run(db, "keys").stdout == "num\nobj\n"


def test_json_string_value_printed_raw(tmp_path):
    db = tmp_path / "cli.json"
    run(db, "set", "s", '"quoted"')
    assert run(db, "get", "s").stdout == "quoted\n"


def test_missing_key_exits_1(tmp_path):
    db = tmp_path / "cli.json"
    r = run(db, "get", "nope")
    assert r.returncode == 1 and r.stdout == ""
    assert run(db, "del", "nope").returncode == 1
    r = run(db, "keys")
    assert (r.returncode, r.stdout) == (0, "")


def test_ttl(tmp_path):
    db = tmp_path / "cli.json"
    assert run(db, "set", "gone", "1", "--ttl", "-1").returncode == 0
    assert run(db, "set", "live", "1", "--ttl", "3600").returncode == 0
    assert run(db, "get", "gone").returncode == 1
    assert run(db, "get", "live").stdout == "1\n"
    assert run(db, "keys").stdout == "live\n"
