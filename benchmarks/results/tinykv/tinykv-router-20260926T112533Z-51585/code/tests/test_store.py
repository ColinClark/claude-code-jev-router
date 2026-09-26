"""Basic CRUD behaviour of Store."""

import pytest

from tinykv.store import Store


@pytest.mark.parametrize(
    "value",
    [
        "hello",
        "",
        "unicode: é中\U0001f600",
        0,
        42,
        -7,
        3.14,
        True,
        False,
        [],
        [1, "two", 3.0, None, False],
        {},
        {"a": 1, "b": "two"},
        {"nested": {"list": [1, {"deep": [True, None]}], "n": 1.5}},
    ],
    ids=lambda v: type(v).__name__ + ":" + repr(v)[:20],
)
def test_set_then_get_roundtrips_json_types(store: Store, value: object) -> None:
    store.set("k", value)
    result = store.get("k")
    assert result == value
    assert type(result) is type(value)


def test_set_none_value_is_present_in_keys(store: Store) -> None:
    store.set("nothing", None)
    assert store.get("nothing") is None
    assert store.keys() == ["nothing"]


def test_get_never_set_key_returns_none(store: Store) -> None:
    assert store.get("missing") is None
    store.set("other", 1)
    assert store.get("missing") is None


def test_set_overwrites_existing_value(store: Store) -> None:
    store.set("k", "first")
    store.set("k", {"second": 2})
    assert store.get("k") == {"second": 2}
    assert store.keys() == ["k"]


def test_delete_removes_key(store: Store) -> None:
    store.set("a", 1)
    store.set("b", 2)
    store.delete("a")
    assert store.get("a") is None
    assert store.keys() == ["b"]
    assert store.get("b") == 2


def test_delete_missing_key_does_not_raise(store: Store) -> None:
    store.delete("never-existed")
    store.set("a", 1)
    store.delete("never-existed")
    assert store.keys() == ["a"]


def test_keys_reflects_current_state(store: Store) -> None:
    assert store.keys() == []
    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)
    assert sorted(store.keys()) == ["a", "b", "c"]
    store.delete("b")
    assert sorted(store.keys()) == ["a", "c"]
    store.set("b", 4)
    assert sorted(store.keys()) == ["a", "b", "c"]
    for k in ("a", "b", "c"):
        store.delete(k)
    assert store.keys() == []


def test_unserializable_value_raises_and_leaves_store_untouched(store: Store) -> None:
    store.set("a", 1)
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert store.keys() == ["a"]
    assert store.get("a") == 1
