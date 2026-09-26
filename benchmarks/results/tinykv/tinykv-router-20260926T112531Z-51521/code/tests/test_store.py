import json
import multiprocessing
import os

import pytest

from tinykv import Store, StoreCorruptError


class FakeClock:
    def __init__(self, now: float = 1_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def db(tmp_path):
    return tmp_path / "db.json"


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(db, clock):
    return Store(db, clock=clock)


def read_file(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def leftover_temp_files(directory):
    return [n for n in os.listdir(directory) if n.endswith(".tmp")]


# ---------------------------------------------------------------- basic CRUD


def test_missing_file_is_empty_store(store, db):
    assert store.get("nope") is None
    assert store.get("nope", "fallback") == "fallback"
    assert store.keys() == []
    assert not db.exists()


def test_set_get_overwrite(store):
    store.set("a", 1)
    assert store.get("a") == 1
    store.set("a", "two")
    assert store.get("a") == "two"


def test_nested_json_values(store):
    value = {"list": [1, 2.5, None, True], "nested": {"s": "héllo", "empty": {}}}
    store.set("doc", value)
    assert store.get("doc") == value


def test_falsy_values_are_not_treated_as_missing(store):
    store.set("zero", 0)
    store.set("none", None)
    assert store.get("zero", "d") == 0
    assert store.get("none", "d") is None
    assert store.keys() == ["none", "zero"]


def test_delete(store):
    store.set("a", 1)
    assert store.delete("a") is True
    assert store.get("a") is None
    assert store.delete("a") is False
    assert store.delete("never") is False


def test_keys_sorted(store):
    for k in ["b", "c", "a"]:
        store.set(k, k)
    assert store.keys() == ["a", "b", "c"]


@pytest.mark.parametrize("bad", [object(), {1, 2}, b"bytes", float("nan"), {(1, 2): "x"}])
def test_non_serializable_rejected_before_touching_file(store, db, bad):
    store.set("keep", 1)
    before = db.read_bytes()
    with pytest.raises(TypeError, match="JSON-serializable"):
        store.set("bad", bad)
    assert db.read_bytes() == before
    assert store.get("bad") is None


def test_non_serializable_rejected_on_empty_store_creates_no_file(store, db):
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert not db.exists()


def test_non_str_key_rejected(store):
    with pytest.raises(TypeError):
        store.set(1, "x")  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        store.get(None)  # type: ignore[arg-type]


@pytest.mark.parametrize("ttl", [0, -1, -0.5, float("nan"), float("inf")])
def test_invalid_ttl_rejected(store, db, ttl):
    with pytest.raises(ValueError):
        store.set("a", 1, ttl=ttl)
    assert not db.exists()


@pytest.mark.parametrize("ttl", ["10", True])
def test_non_numeric_ttl_rejected(store, ttl):
    with pytest.raises(TypeError):
        store.set("a", 1, ttl=ttl)


def test_update(store):
    assert store.update("n", lambda v: v + 1, default=0) == 1
    assert store.update("n", lambda v: v + 1, default=0) == 2
    assert store.get("n") == 2


def test_update_failure_leaves_file_unchanged(store, db):
    store.set("n", 1)
    before = db.read_bytes()
    with pytest.raises(TypeError):
        store.update("n", lambda v: object())

    def boom(v):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        store.update("n", boom)
    assert db.read_bytes() == before
    assert leftover_temp_files(db.parent) == []


def test_corrupt_file_raises(db):
    db.write_text("{not json")
    with pytest.raises(StoreCorruptError):
        Store(db).get("a")
    with pytest.raises(StoreCorruptError):
        Store(db).set("a", 1)
    assert db.read_text() == "{not json"


# ---------------------------------------------------------------- TTL


def test_ttl_visible_before_expiry_invisible_at_and_after(store, clock):
    store.set("t", "v", ttl=10)
    store.set("p", "perm")
    clock.advance(9.999)
    assert store.get("t") == "v"
    assert store.keys() == ["p", "t"]
    clock.advance(0.001)  # exactly at expiry
    assert store.get("t") is None
    assert store.get("t", "d") == "d"
    assert store.keys() == ["p"]
    clock.advance(100)
    assert store.get("t") is None
    assert store.keys() == ["p"]


def test_expired_entry_removed_from_file_on_next_set(store, db, clock):
    store.set("t", 1, ttl=5)
    clock.advance(5)
    assert "t" in read_file(db)  # lazy: still physically present until a write
    store.set("other", 2)
    assert set(read_file(db)) == {"other"}


def test_expired_entry_removed_from_file_on_next_delete(store, db, clock):
    store.set("t", 1, ttl=5)
    store.set("keep", 1)
    clock.advance(6)
    assert store.delete("unrelated") is False
    assert set(read_file(db)) == {"keep"}


def test_delete_expired_key_returns_false_and_purges(store, db, clock):
    store.set("t", 1, ttl=5)
    clock.advance(5)
    assert store.delete("t") is False
    assert read_file(db) == {}


def test_set_without_ttl_clears_previous_ttl(store, db, clock):
    store.set("k", 1, ttl=5)
    store.set("k", 2)
    assert read_file(db)["k"]["expires_at"] is None
    clock.advance(1000)
    assert store.get("k") == 2


def test_update_on_expired_key_uses_default(store, clock):
    store.set("n", 41, ttl=1)
    clock.advance(1)
    assert store.update("n", lambda v: v + 1, default=0) == 1


def test_expiry_is_absolute_across_instances(db, clock):
    Store(db, clock=clock).set("t", "v", ttl=10)
    assert read_file(db)["t"]["expires_at"] == clock.now + 10
    later = FakeClock(clock.now + 10)
    assert Store(db, clock=later).get("t") is None
    earlier = FakeClock(clock.now + 5)
    assert Store(db, clock=earlier).get("t") == "v"


# ---------------------------------------------------------------- persistence


def test_persistence_across_instances(db):
    Store(db).set("a", {"x": [1, 2]})
    Store(db).set("b", "B")
    other = Store(db)
    assert other.get("a") == {"x": [1, 2]}
    assert other.keys() == ["a", "b"]
    assert other.delete("a") is True
    assert Store(db).keys() == ["b"]


def test_file_is_valid_json_and_no_temp_files(store, db):
    for i in range(20):
        store.set(f"k{i}", i, ttl=None if i % 2 else 60)
    store.delete("k0")
    data = read_file(db)
    assert isinstance(data, dict)
    assert len(data) == 19
    assert leftover_temp_files(db.parent) == []
    assert sorted(os.listdir(db.parent)) == ["db.json", "db.json.lock"]


def test_creates_missing_parent_dir(tmp_path):
    db = tmp_path / "sub" / "dir" / "db.json"
    s = Store(db)
    assert s.get("a") is None
    s.set("a", 1)
    assert read_file(db)["a"]["value"] == 1


def test_temp_file_cleaned_up_when_replace_fails(store, db, monkeypatch):
    store.set("a", 1)
    before = db.read_bytes()

    def failing_replace(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", failing_replace)
    with pytest.raises(OSError, match="simulated"):
        store.set("b", 2)
    monkeypatch.undo()
    assert db.read_bytes() == before
    assert leftover_temp_files(db.parent) == []


# ---------------------------------------------------------------- multi-process

N_PROCS = 8
N_ITERS = 50


def _worker(path: str, worker_id: int, iterations: int) -> None:
    store = Store(path)
    for i in range(iterations):
        store.update("counter", lambda v: v + 1, default=0)
        store.set(f"w{worker_id}-{i}", worker_id)


def test_multiprocess_concurrent_updates(db):
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(target=_worker, args=(str(db), wid, N_ITERS)) for wid in range(N_PROCS)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    for p in procs:
        if p.is_alive():
            p.terminate()
    assert [p.exitcode for p in procs] == [0] * N_PROCS

    store = Store(db)
    assert store.get("counter") == N_PROCS * N_ITERS
    expected = {f"w{w}-{i}" for w in range(N_PROCS) for i in range(N_ITERS)}
    keys = set(store.keys())
    assert expected <= keys
    assert keys == expected | {"counter"}
    assert leftover_temp_files(db.parent) == []
