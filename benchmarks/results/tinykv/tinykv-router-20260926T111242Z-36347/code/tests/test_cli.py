import json
import subprocess
import sys

from tinykv import Store
from tinykv.__main__ import main


def run(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db), *args],
        capture_output=True,
        text=True,
    )


def test_set_get_string(tmp_path):
    db = tmp_path / "db.json"
    assert run(db, "set", "k", "hello").returncode == 0
    r = run(db, "get", "k")
    assert r.returncode == 0
    assert json.loads(r.stdout) == "hello"


def test_set_get_json(tmp_path):
    db = tmp_path / "db.json"
    assert run(db, "set", "n", "42").returncode == 0
    assert run(db, "set", "o", '{"a":1}').returncode == 0
    assert json.loads(run(db, "get", "n").stdout) == 42
    assert json.loads(run(db, "get", "o").stdout) == {"a": 1}


def test_keys_and_persistence(tmp_path):
    db = tmp_path / "db.json"
    run(db, "set", "a", "1")
    run(db, "set", "b", "2")
    r = run(db, "keys")
    assert r.returncode == 0
    assert sorted(r.stdout.split()) == ["a", "b"]


def test_del(tmp_path):
    db = tmp_path / "db.json"
    run(db, "set", "a", "1")
    assert run(db, "del", "a").returncode == 0
    r = run(db, "del", "a")
    assert r.returncode == 1
    assert r.stderr


def test_get_missing(tmp_path):
    r = run(tmp_path / "db.json", "get", "nope")
    assert r.returncode == 1
    assert r.stderr


def test_get_expired(tmp_path):
    db = tmp_path / "db.json"
    Store(str(db), clock=lambda: 1000.0).set("old", "v", ttl=1)
    r = run(db, "get", "old")
    assert r.returncode == 1


def test_invalid_ttl(tmp_path):
    r = run(tmp_path / "db.json", "set", "k", "v", "--ttl", "0")
    assert r.returncode == 2
    assert r.stderr


def test_main_in_process(tmp_path, capsys):
    db = str(tmp_path / "db.json")
    assert main(["--db", db, "set", "x", "null"]) == 0
    assert main(["--db", db, "get", "x"]) == 0
    assert capsys.readouterr().out.strip() == "null"
    assert main(["--db", db, "get", "missing"]) == 1
