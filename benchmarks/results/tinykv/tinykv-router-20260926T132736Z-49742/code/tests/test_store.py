import json

import pytest

import tinykv.store
from tinykv import Store


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "db.json")


@pytest.mark.parametrize(
    "value",
    ["hello", 42, 3.5, True, False, None, [1, "two", 3.0], {"a": 1, "b": [True, None]}],
)
def test_set_get_json_types(store, value):
    store.set("k", value)
    assert store.get("k", "sentinel") == value


def test_get_missing_returns_default(store):
    assert store.get("missing") is None
    assert store.get("missing", "fallback") == "fallback"


def test_delete_removes_key(store):
    store.set("k", 1)
    store.delete("k")
    assert store.get("k") is None
    assert "k" not in store.keys()


def test_delete_missing_key_does_not_raise(store):
    store.delete("nope")
    store.set("k", 1)
    store.delete("nope")
    assert store.keys() == ["k"]


def test_keys_reflects_live_set(store):
    assert store.keys() == []
    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)
    assert sorted(store.keys()) == ["a", "b", "c"]
    store.delete("b")
    assert sorted(store.keys()) == ["a", "c"]


def test_overwrite_value(store):
    store.set("k", "old")
    store.set("k", {"new": True})
    assert store.get("k") == {"new": True}
    assert store.keys() == ["k"]


class FakeClock:
    def __init__(self, now=1_000_000.0):
        self.now = now

    def __call__(self):
        return self.now


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(tinykv.store.time, "time", fake)
    return fake


def test_key_live_before_ttl_elapses(store, clock):
    store.set("k", "v", ttl=10)
    clock.now += 9.999
    assert store.get("k") == "v"
    assert store.keys() == ["k"]


def test_key_expires_after_ttl(store, clock):
    store.set("k", "v", ttl=10)
    store.set("forever", 1)
    clock.now += 10
    assert store.get("k") is None
    assert store.get("k", "default") == "default"
    assert store.keys() == ["forever"]


def test_expired_key_stays_in_file_until_next_write(store, clock, tmp_path):
    db = tmp_path / "db.json"
    store.set("k", "v", ttl=5)
    clock.now += 6
    assert store.get("k") is None
    assert "k" in json.loads(db.read_text())
    assert Store(db).get("k") is None

    store.set("other", 1)
    assert "k" not in json.loads(db.read_text())


def test_delete_purges_expired_keys(store, clock, tmp_path):
    store.set("k", "v", ttl=5)
    store.set("x", 1)
    clock.now += 6
    store.delete("x")
    assert json.loads((tmp_path / "db.json").read_text()) == {}


def test_overwrite_without_ttl_clears_expiry(store, clock):
    store.set("k", "v", ttl=5)
    store.set("k", "v2")
    clock.now += 100
    assert store.get("k") == "v2"


def test_real_ttl_expiry_sanity(store):
    import time

    store.set("k", "v", ttl=0.05)
    assert store.get("k") == "v"
    time.sleep(0.1)
    assert store.get("k") is None
    assert store.keys() == []


def test_persistence_across_instances(tmp_path):
    db = tmp_path / "db.json"
    first = Store(db)
    first.set("a", 1)
    first.set("b", {"nested": [1, 2]})
    first.set("c", "three")
    first.delete("c")

    second = Store(db)
    assert sorted(second.keys()) == ["a", "b"]
    assert second.get("a") == 1
    assert second.get("b") == {"nested": [1, 2]}
    assert second.get("c") is None

    second.set("d", True)
    assert first.get("d") is True


def test_missing_file_is_empty_store(tmp_path):
    store = Store(tmp_path / "does-not-exist.json")
    assert store.keys() == []
    assert store.get("k") is None
