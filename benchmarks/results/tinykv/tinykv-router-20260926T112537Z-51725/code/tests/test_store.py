import json
import os

import pytest

import tinykv
from tinykv import Store
from tinykv import store as store_mod


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def db(tmp_path):
    return tmp_path / "db.json"


@pytest.fixture
def store(db, clock) -> Store:
    return Store(db, clock=clock)


def read_disk(path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def test_exported_from_package():
    assert tinykv.Store is Store
    assert "Store" in tinykv.__all__


def test_missing_file_is_empty_store(store, db):
    assert not db.exists()
    assert store.get("nope") is None
    assert store.get("nope", "fallback") == "fallback"
    assert store.keys() == []


def test_basic_crud(store):
    store.set("a", 1)
    store.set("b", {"nested": [1, 2, "x"], "ok": True, "n": None})
    assert store.get("a") == 1
    assert store.get("b") == {"nested": [1, 2, "x"], "ok": True, "n": None}

    store.set("a", "overwritten")
    assert store.get("a") == "overwritten"

    assert store.delete("a") is True
    assert store.get("a") is None
    assert store.keys() == ["b"]


def test_delete_missing_key_returns_false(store, db):
    assert store.delete("ghost") is False
    store.set("x", 1)
    assert store.delete("ghost") is False
    assert store.keys() == ["x"]


def test_keys_sorted_and_live_only(store, clock):
    for k in ["pear", "apple", "zebra", "mango"]:
        store.set(k, k.upper())
    store.set("ephemeral", 1, ttl=5)
    assert store.keys() == ["apple", "ephemeral", "mango", "pear", "zebra"]
    clock.advance(5)
    assert store.keys() == ["apple", "mango", "pear", "zebra"]


def test_ttl_expiry_with_fake_clock(store, clock):
    store.set("k", "v", ttl=10)
    clock.advance(9.999)
    assert store.get("k") == "v"
    clock.advance(0.001)
    assert store.get("k") is None
    assert store.get("k", "dflt") == "dflt"
    assert store.delete("k") is False


def test_absolute_expiry_stored_on_disk(store, db, clock):
    store.set("k", "v", ttl=30)
    store.set("forever", 1)
    disk = read_disk(db)
    assert disk["k"]["expires_at"] == pytest.approx(clock.now + 30)
    assert disk["forever"]["expires_at"] is None


def test_expired_key_dropped_from_disk_on_next_write(store, db, clock):
    store.set("short", 1, ttl=1)
    store.set("keep", 2)
    clock.advance(2)
    # Lazy: reads do not rewrite the file.
    assert store.get("short") is None
    assert "short" in read_disk(db)
    # The next write prunes all expired entries.
    store.set("other", 3)
    disk = read_disk(db)
    assert "short" not in disk
    assert set(disk) == {"keep", "other"}


def test_delete_prunes_expired_entries(store, db, clock):
    store.set("short", 1, ttl=1)
    store.set("keep", 2)
    clock.advance(2)
    assert store.delete("missing") is False
    assert set(read_disk(db)) == {"keep"}


def test_set_without_ttl_clears_previous_ttl(store, db, clock):
    store.set("k", "v1", ttl=5)
    store.set("k", "v2")
    assert read_disk(db)["k"]["expires_at"] is None
    clock.advance(1_000)
    assert store.get("k") == "v2"


def test_set_with_new_ttl_replaces_old_ttl(store, clock):
    store.set("k", "v", ttl=100)
    store.set("k", "v", ttl=1)
    clock.advance(2)
    assert store.get("k") is None


@pytest.mark.parametrize("bad", [0, -1, -0.5, 0.0])
def test_ttl_must_be_positive(store, db, bad):
    with pytest.raises(ValueError):
        store.set("k", "v", ttl=bad)
    assert not db.exists()


@pytest.mark.parametrize("bad", ["10", True, [1]])
def test_ttl_must_be_number(store, bad):
    with pytest.raises(TypeError):
        store.set("k", "v", ttl=bad)


def test_float_ttl_accepted(store, clock):
    store.set("k", "v", ttl=0.5)
    assert store.get("k") == "v"
    clock.advance(0.5)
    assert store.get("k") is None


def test_persistence_across_instances(db, clock):
    Store(db, clock=clock).set("a", [1, 2, 3])
    Store(db, clock=clock).set("b", "two", ttl=60)
    fresh = Store(db, clock=clock)
    assert fresh.get("a") == [1, 2, 3]
    assert fresh.get("b") == "two"
    assert fresh.keys() == ["a", "b"]
    clock.advance(61)
    assert Store(db, clock=clock).keys() == ["a"]


def test_str_path_accepted(tmp_path):
    s = Store(str(tmp_path / "db.json"))
    s.set("k", 1)
    assert Store(str(tmp_path / "db.json")).get("k") == 1


def _stray_files(directory, db):
    allowed = {db.name, db.name + ".lock"}
    return sorted(p.name for p in directory.iterdir() if p.name not in allowed)


def test_atomic_write_leaves_no_temp_files(store, db, tmp_path):
    for i in range(20):
        store.set(f"k{i}", i)
    store.delete("k0")
    store.update("counter", lambda n: n + 1, default=0)
    assert _stray_files(tmp_path, db) == []


def test_failed_replace_cleans_temp_and_keeps_file(store, db, tmp_path, monkeypatch):
    store.set("a", 1)
    before = db.read_bytes()

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(store_mod.os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        store.set("b", 2)
    monkeypatch.undo()

    assert db.read_bytes() == before
    assert _stray_files(tmp_path, db) == []
    assert store.keys() == ["a"]


def test_non_serializable_value_rejected_file_unchanged(store, db, tmp_path):
    store.set("a", 1)
    before = db.read_bytes()
    mtime = os.stat(db).st_mtime_ns

    for bad in [object(), {1, 2}, {"nested": object()}, float("nan")]:
        with pytest.raises(TypeError):
            store.set("bad", bad)

    assert db.read_bytes() == before
    assert os.stat(db).st_mtime_ns == mtime
    assert _stray_files(tmp_path, db) == []
    assert store.get("bad") is None


def test_non_serializable_value_rejected_on_missing_file(store, db):
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert not db.exists()


def test_non_str_key_rejected(store):
    with pytest.raises(TypeError):
        store.set(1, "v")  # type: ignore[arg-type]


def test_update_increments_and_respects_default(store):
    assert store.update("n", lambda v: v + 1, default=0) == 1
    assert store.update("n", lambda v: v + 1, default=0) == 2
    assert store.get("n") == 2


def test_update_treats_expired_as_missing(store, clock):
    store.set("n", 100, ttl=1)
    clock.advance(1)
    assert store.update("n", lambda v: v + 1, default=0) == 1


def test_update_non_serializable_result_rejected(store, db):
    store.set("n", 1)
    before = db.read_bytes()
    with pytest.raises(TypeError):
        store.update("n", lambda v: object())
    assert db.read_bytes() == before


def test_update_exception_in_fn_leaves_file_unchanged(store, db):
    store.set("n", 1)
    before = db.read_bytes()

    def fail(_):
        raise RuntimeError("nope")

    with pytest.raises(RuntimeError):
        store.update("n", fail)
    assert db.read_bytes() == before


def test_update_ttl(store, clock):
    store.update("n", lambda v: v + 1, default=0, ttl=5)
    clock.advance(5)
    assert store.get("n") is None
