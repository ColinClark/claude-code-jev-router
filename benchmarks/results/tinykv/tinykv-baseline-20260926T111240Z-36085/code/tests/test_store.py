import json
import multiprocessing as mp

import pytest

from tinykv import Store


class FakeClock:
    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def db(tmp_path):
    return tmp_path / "db.json"


# -- CRUD ------------------------------------------------------------------


def test_get_missing_returns_default(db):
    store = Store(db)
    assert store.get("nope") is None
    assert store.get("nope", default=42) == 42
    assert store.keys() == []


def test_set_get_overwrite_delete(db):
    store = Store(db)
    store.set("a", 1)
    store.set("b", {"nested": [1, 2, None]})
    assert store.get("a") == 1
    assert store.get("b") == {"nested": [1, 2, None]}
    assert store.keys() == ["a", "b"]

    store.set("a", "two")
    assert store.get("a") == "two"

    assert store.delete("a") is True
    assert store.get("a") is None
    assert store.delete("a") is False
    assert store.keys() == ["b"]


def test_non_serializable_value_rejected_without_writing(db):
    store = Store(db)
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert not db.exists()


def test_atomic_write_leaves_no_temp_files(db):
    store = Store(db)
    for i in range(5):
        store.set(f"k{i}", i)
    leftovers = [p.name for p in db.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


# -- TTL -------------------------------------------------------------------


def test_ttl_expiry_with_fake_clock(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("short", "x", ttl=10)
    store.set("forever", "y")

    clock.advance(9.999)
    assert store.get("short") == "x"
    assert store.keys() == ["forever", "short"]

    clock.advance(0.001)  # exactly at expiry -> expired
    assert store.get("short") is None
    assert store.keys() == ["forever"]
    assert store.delete("short") is False


def test_expired_keys_dropped_on_next_write(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("gone", 1, ttl=5)
    clock.advance(6)

    # Lazy: still physically on disk until a write happens.
    assert "gone" in json.loads(db.read_text())

    store.set("other", 2)
    on_disk = json.loads(db.read_text())
    assert "gone" not in on_disk
    assert "other" in on_disk


def test_set_without_ttl_clears_previous_ttl(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("k", 1, ttl=5)
    store.set("k", 2)
    clock.advance(100)
    assert store.get("k") == 2


@pytest.mark.parametrize("ttl", [0, -1])
def test_non_positive_ttl_rejected(db, ttl):
    with pytest.raises(ValueError):
        Store(db).set("k", 1, ttl=ttl)


# -- persistence -----------------------------------------------------------


def test_persistence_across_instances(db):
    clock = FakeClock()
    Store(db, clock=clock).set("a", [1, 2, 3])
    Store(db, clock=clock).set("t", "v", ttl=30)

    reopened = Store(db, clock=clock)
    assert reopened.get("a") == [1, 2, 3]
    assert reopened.get("t") == "v"

    clock.advance(31)
    assert Store(db, clock=clock).get("t") is None


# -- concurrency -----------------------------------------------------------

WORKERS = 8
INCREMENTS = 50


def _increment_worker(path: str, n: int, start) -> None:
    store = Store(path)
    start.wait()
    for _ in range(n):
        with store._write() as (data, _now):
            entry = data.get("counter")
            data["counter"] = {
                "value": (entry["value"] if entry else 0) + 1,
                "expires_at": None,
            }


def _distinct_key_worker(path: str, worker: int, n: int, start) -> None:
    store = Store(path)
    start.wait()
    for i in range(n):
        store.set(f"w{worker}-{i}", i)


def _run(target, args_for):
    ctx = mp.get_context("spawn")
    start = ctx.Event()
    procs = [ctx.Process(target=target, args=(*args_for(w), start)) for w in range(WORKERS)]
    for p in procs:
        p.start()
    start.set()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0


def test_concurrent_increments_lose_no_updates(db):
    """Locked read-modify-write from many processes: the counter must be exact."""
    _run(_increment_worker, lambda w: (str(db), INCREMENTS))
    assert Store(db).get("counter") == WORKERS * INCREMENTS


def test_concurrent_sets_lose_no_keys(db):
    """Each public set() is a read-modify-write of the whole file; none may be lost."""
    _run(_distinct_key_worker, lambda w: (str(db), w, INCREMENTS))
    assert len(Store(db).keys()) == WORKERS * INCREMENTS
