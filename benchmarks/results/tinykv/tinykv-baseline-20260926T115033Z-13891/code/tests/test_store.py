from __future__ import annotations

import json
from pathlib import Path

import pytest

from tinykv.store import Store


def test_get_missing_returns_none_and_default(store: Store) -> None:
    assert store.get("nope") is None
    assert store.get("nope", "fallback") == "fallback"


def test_set_get_delete_roundtrip(store: Store) -> None:
    store.set("a", 1)
    store.set("b", {"nested": [1, 2, {"x": None}]})
    store.set("c", "text")
    assert store.get("a") == 1
    assert store.get("b") == {"nested": [1, 2, {"x": None}]}
    assert store.get("c") == "text"
    assert store.keys() == ["a", "b", "c"]

    assert store.delete("b") is True
    assert store.get("b") is None
    assert store.keys() == ["a", "c"]
    assert store.delete("b") is False


def test_set_overwrites_existing_value(store: Store) -> None:
    store.set("k", "old")
    store.set("k", "new")
    assert store.get("k") == "new"
    assert store.keys() == ["k"]


def test_falsy_values_are_stored_and_returned(store: Store) -> None:
    store.set("zero", 0)
    store.set("empty", "")
    store.set("null", None)
    store.set("false", False)
    assert store.get("zero") == 0
    assert store.get("empty") == ""
    assert store.get("null") is None
    assert store.get("false") is False
    assert store.keys() == ["empty", "false", "null", "zero"]


def test_non_serializable_value_is_rejected_before_writing(store: Store, db_path: Path) -> None:
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert not db_path.exists()


def test_invalid_ttl_rejected(store: Store) -> None:
    with pytest.raises(ValueError):
        store.set("k", 1, ttl=0)
    with pytest.raises(ValueError):
        store.set("k", 1, ttl=-5)
    with pytest.raises(TypeError):
        store.set("k", 1, ttl="10")  # type: ignore[arg-type]


def test_persistence_across_instances(db_path: Path) -> None:
    first = Store(db_path)
    first.set("alpha", [1, 2, 3])
    first.set("beta", "b")
    first.delete("beta")

    second = Store(db_path)
    assert second.get("alpha") == [1, 2, 3]
    assert second.get("beta") is None
    assert second.keys() == ["alpha"]

    second.set("gamma", True)
    third = Store(db_path)
    assert third.keys() == ["alpha", "gamma"]


def test_on_disk_format_is_json_and_no_temp_files_remain(store: Store, db_path: Path) -> None:
    store.set("k", {"v": 1})
    raw = json.loads(db_path.read_text())
    assert raw == {"k": {"value": {"v": 1}, "expires": None}}
    leftovers = [p.name for p in db_path.parent.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_empty_or_missing_file_is_treated_as_empty(db_path: Path) -> None:
    db_path.write_text("")
    s = Store(db_path)
    assert s.keys() == []
    s.set("k", 1)
    assert Store(db_path).get("k") == 1


def test_corrupt_file_raises(db_path: Path) -> None:
    db_path.write_text("[1, 2, 3]")
    with pytest.raises(ValueError):
        Store(db_path).keys()


def test_nested_directory_is_created(tmp_path: Path) -> None:
    path = tmp_path / "deep" / "er" / "data.json"
    Store(path).set("k", 1)
    assert Store(path).get("k") == 1
