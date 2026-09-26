import json
import os

import pytest

from tinykv.store import Store


def test_get_missing_returns_default(store):
    assert store.get("nope") is None
    assert store.get("nope", "dflt") == "dflt"


def test_set_get_delete_roundtrip(store):
    store.set("a", 1)
    store.set("b", {"nested": [1, 2, "three", None, True]})
    assert store.get("a") == 1
    assert store.get("b") == {"nested": [1, 2, "three", None, True]}
    assert store.keys() == ["a", "b"]
    assert "a" in store
    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.get("a") is None
    assert store.keys() == ["b"]


def test_overwrite_replaces_value(store):
    store.set("k", "v1")
    store.set("k", "v2")
    assert store.get("k") == "v2"
    assert store.keys() == ["k"]


def test_non_serializable_value_rejected(store):
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert store.keys() == []


def test_ttl_expiry_without_sleeping(store, clock):
    store.set("temp", "x", ttl=10)
    store.set("perm", "y")
    assert store.get("temp") == "x"
    clock.advance(9.999)
    assert store.get("temp") == "x"
    clock.advance(0.001)
    assert store.get("temp") is None
    assert "temp" not in store
    assert store.keys() == ["perm"]


def test_expired_keys_dropped_from_file_on_next_write(store, clock, db_path):
    store.set("temp", "x", ttl=5)
    clock.advance(6)
    # Reads are lazy: the expired entry is still physically present.
    assert "temp" in json.loads(db_path.read_text())
    store.set("other", 1)
    assert "temp" not in json.loads(db_path.read_text())
    assert store.keys() == ["other"]


def test_overwrite_clears_ttl(store, clock):
    store.set("k", 1, ttl=5)
    store.set("k", 2)
    clock.advance(100)
    assert store.get("k") == 2


def test_invalid_ttl_rejected(store):
    with pytest.raises(ValueError):
        store.set("k", 1, ttl=0)
    with pytest.raises(ValueError):
        store.set("k", 1, ttl=-1)


def test_update_applies_function(store):
    assert store.update("n", lambda v: v + 1, default=0) == 1
    assert store.update("n", lambda v: v + 1, default=0) == 2
    assert store.get("n") == 2


def test_persistence_across_instances(db_path):
    Store(db_path).set("a", [1, 2, 3])
    Store(db_path).set("b", "bee")
    fresh = Store(db_path)
    assert fresh.get("a") == [1, 2, 3]
    assert fresh.get("b") == "bee"
    assert fresh.keys() == ["a", "b"]


def test_ttl_persists_across_instances(db_path, clock):
    Store(db_path, clock=clock).set("t", 1, ttl=30)
    later = Store(db_path, clock=clock)
    clock.advance(31)
    assert later.get("t") is None


def test_write_is_atomic_no_temp_files_left(store, db_path):
    store.set("a", 1)
    leftovers = [n for n in os.listdir(db_path.parent) if n.endswith(".tmp")]
    assert leftovers == []
    assert set(os.listdir(db_path.parent)) == {db_path.name, db_path.name + ".lock"}


def test_write_replaces_file_inode_atomically(store, db_path):
    store.set("a", 1)
    before = os.stat(db_path).st_ino
    store.set("a", 2)
    after = os.stat(db_path).st_ino
    assert before != after  # os.replace swapped in a new file
    assert json.loads(db_path.read_text()) == {"a": {"value": 2, "expires": None}}


def test_missing_parent_directory_created(tmp_path):
    path = tmp_path / "deep" / "er" / "db.json"
    Store(path).set("a", 1)
    assert Store(path).get("a") == 1


def test_corrupt_top_level_rejected(db_path):
    db_path.write_text("[1, 2, 3]")
    with pytest.raises(ValueError):
        Store(db_path).get("a")
