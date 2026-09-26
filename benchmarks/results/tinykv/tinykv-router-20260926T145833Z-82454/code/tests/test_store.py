import json
import multiprocessing as mp

import pytest

from tinykv import Store


class FakeClock:
    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def db(tmp_path):
    return tmp_path / "db.json"


# -- CRUD -------------------------------------------------------------------


def test_get_missing_returns_default(db):
    store = Store(db)
    assert store.get("nope") is None
    assert store.get("nope", 42) == 42
    assert store.keys() == []


def test_set_get_overwrite_delete(db):
    store = Store(db)
    store.set("a", 1)
    store.set("b", {"nested": [1, 2, "x"]})
    assert store.get("a") == 1
    assert store.get("b") == {"nested": [1, 2, "x"]}
    assert store.keys() == ["a", "b"]

    store.set("a", "two")
    assert store.get("a") == "two"

    assert store.delete("a") is True
    assert store.get("a") is None
    assert store.delete("a") is False
    assert store.keys() == ["b"]


def test_null_value_is_distinct_from_missing(db):
    store = Store(db)
    store.set("n", None)
    assert "n" in store
    assert store.keys() == ["n"]


def test_non_json_value_rejected_without_writing(db):
    store = Store(db)
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert not db.exists()


def test_invalid_ttl_rejected(db):
    with pytest.raises(ValueError):
        Store(db).set("k", 1, ttl=0)


# -- TTL (fake clock, no sleeps) ----------------------------------------------


def test_ttl_expiry_is_lazy_and_hidden(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("short", "x", ttl=10)
    store.set("forever", "y")

    clock.now += 9.9
    assert store.get("short") == "x"

    clock.now += 0.1  # exactly at expiry
    assert store.get("short") is None
    assert "short" not in store
    assert store.keys() == ["forever"]
    # Lazy: a read does not rewrite the file, the expired entry is still on disk.
    assert "short" in json.loads(db.read_text())


def test_expired_keys_dropped_on_next_write(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("short", "x", ttl=5)
    clock.now += 5
    store.set("other", 1)
    on_disk = json.loads(db.read_text())
    assert "short" not in on_disk
    assert set(on_disk) == {"other"}


def test_delete_expired_key_reports_missing(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("k", 1, ttl=1)
    clock.now += 2
    assert store.delete("k") is False


def test_overwrite_clears_ttl(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("k", 1, ttl=1)
    store.set("k", 2)
    clock.now += 100
    assert store.get("k") == 2


# -- persistence ------------------------------------------------------------------


def test_persistence_across_instances(db):
    clock = FakeClock()
    Store(db, clock=clock).set("a", [1, 2, 3])
    Store(db, clock=clock).set("t", "v", ttl=30)

    reopened = Store(db, clock=clock)
    assert reopened.get("a") == [1, 2, 3]
    assert reopened.get("t") == "v"
    clock.now += 31
    assert Store(db, clock=clock).get("t") is None


def test_atomic_write_leaves_no_temp_files(db):
    store = Store(db)
    for i in range(5):
        store.set(f"k{i}", i)
    leftovers = [p.name for p in db.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_creates_parent_directory(tmp_path):
    store = Store(tmp_path / "nested" / "dir" / "db.json")
    store.set("a", 1)
    assert store.get("a") == 1


# -- multi-process concurrency --------------------------------------------------


def _increment(path: str, key: str, n: int) -> None:
    store = Store(path)
    for _ in range(n):
        with store._write() as data:
            data[key] = {"v": data.get(key, {"v": 0})["v"] + 1, "e": None}


def _set_distinct(path: str, worker: int, n: int) -> None:
    store = Store(path)
    for i in range(n):
        store.set(f"w{worker}-{i}", i)


def _run(target, args_list):
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=target, args=args) for args in args_list]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0


def test_concurrent_writers_no_lost_updates(db):
    workers, per_worker = 6, 40
    _run(_set_distinct, [(str(db), w, per_worker) for w in range(workers)])
    keys = Store(db).keys()
    assert len(keys) == workers * per_worker


def test_concurrent_read_modify_write_counter(db):
    workers, per_worker = 6, 40
    _run(_increment, [(str(db), "counter", per_worker) for _ in range(workers)])
    assert Store(db).get("counter") == workers * per_worker
