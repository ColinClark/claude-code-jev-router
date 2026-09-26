"""Basic CRUD behaviour of tinykv.Store."""

from __future__ import annotations

import pytest

from tinykv.store import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "db.json")


@pytest.mark.parametrize(
    "value",
    [
        "hello",
        "",
        42,
        0,
        -7,
        3.14,
        True,
        False,
        None,
        [1, "two", 3.0, None],
        {"a": 1, "b": [1, 2], "c": {"nested": True}},
    ],
)
def test_set_get_json_types(store, value):
    store.set("k", value)
    assert store.get("k", "sentinel") == value


def test_overwrite(store):
    store.set("k", 1)
    store.set("k", "two")
    assert store.get("k") == "two"
    assert store.keys() == ["k"]


def test_delete(store):
    store.set("a", 1)
    store.set("b", 2)
    store.delete("a")
    assert store.get("a") is None
    assert store.get("b") == 2
    assert store.keys() == ["b"]


def test_delete_missing_is_noop(store):
    store.delete("nope")
    assert store.keys() == []


def test_keys_reflect_contents(store):
    assert store.keys() == []
    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)
    assert sorted(store.keys()) == ["a", "b", "c"]
    store.delete("b")
    assert sorted(store.keys()) == ["a", "c"]


def test_get_missing_default_none(store):
    assert store.get("missing") is None


def test_get_missing_custom_default(store):
    assert store.get("missing", "fallback") == "fallback"
    marker = object()
    assert store.get("missing", marker) is marker


def test_stored_none_is_not_default(store):
    store.set("k", None)
    assert store.get("k", "default") is None
    assert "k" in store.keys()


def test_non_serializable_value_rejected(store):
    with pytest.raises(TypeError):
        store.set("k", object())
    assert store.keys() == []
