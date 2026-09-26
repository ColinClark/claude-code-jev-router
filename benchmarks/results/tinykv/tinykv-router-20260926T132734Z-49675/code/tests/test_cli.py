"""CLI tests calling tinykv.__main__.main directly."""

from __future__ import annotations

import json

import pytest

import tinykv.store
from tinykv.__main__ import main


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "db.json")


def run(db, *args):
    return main(["--db", db, *args])


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("42", 42),
        ("3.5", 3.5),
        ("true", True),
        ("null", None),
        ('"quoted"', "quoted"),
        ("[1, 2]", [1, 2]),
        ('{"a": 1}', {"a": 1}),
        ("plain text", "plain text"),  # not valid JSON -> raw string fallback
    ],
)
def test_set_then_get(db, capsys, raw, expected):
    assert run(db, "set", "k", raw) == 0
    capsys.readouterr()
    assert run(db, "get", "k") == 0
    out = capsys.readouterr().out
    assert json.loads(out) == expected
    assert out == json.dumps(expected) + "\n"


def test_get_missing_exits_1(db, capsys):
    assert run(db, "get", "nope") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "key not found: nope" in captured.err


def test_del(db, capsys):
    run(db, "set", "k", "1")
    assert run(db, "del", "k") == 0
    assert run(db, "get", "k") == 1
    assert "key not found: k" in capsys.readouterr().err


def test_del_missing_exits_0(db):
    assert run(db, "del", "nope") == 0


def test_keys(db, capsys):
    assert run(db, "keys") == 0
    assert capsys.readouterr().out == ""
    run(db, "set", "a", "1")
    run(db, "set", "b", "2")
    assert run(db, "keys") == 0
    assert sorted(capsys.readouterr().out.split()) == ["a", "b"]


def test_get_ttl_expired_exits_1(db, capsys, monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr(tinykv.store.time, "time", lambda: now[0])
    assert run(db, "set", "k", "v", "--ttl", "5") == 0
    assert run(db, "get", "k") == 0
    assert json.loads(capsys.readouterr().out) == "v"

    now[0] += 6
    assert run(db, "get", "k") == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "key not found: k" in captured.err


def test_missing_db_arg_errors(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["keys"])
    assert exc.value.code != 0
