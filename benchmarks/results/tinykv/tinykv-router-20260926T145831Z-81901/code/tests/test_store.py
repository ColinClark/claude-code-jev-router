import json
import os
import subprocess
import sys
import textwrap

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


@pytest.fixture
def clock():
    return FakeClock()


# CRUD


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
    store.set("a", "changed")
    assert store.get("a") == "changed"
    assert store.keys() == ["a", "b"]
    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.get("a") is None
    assert store.keys() == ["b"]


def test_null_value_is_distinct_from_missing(db):
    store = Store(db)
    store.set("n", None)
    assert "n" in store
    assert store.get("n", "default") is None
    assert "other" not in store


def test_non_serializable_value_rejected(db):
    store = Store(db)
    with pytest.raises(TypeError):
        store.set("bad", object())
    assert not db.exists()


def test_invalid_ttl_rejected(db):
    with pytest.raises(ValueError):
        Store(db).set("k", 1, ttl=0)


# TTL


def test_ttl_expiry(db, clock):
    store = Store(db, clock=clock)
    store.set("short", "v", ttl=10)
    store.set("forever", "v")
    clock.advance(9.9)
    assert store.get("short") == "v"
    assert store.keys() == ["forever", "short"]
    clock.advance(0.1)
    assert store.get("short") is None
    assert "short" not in store
    assert store.keys() == ["forever"]
    assert store.get("forever") == "v"


def test_expired_keys_dropped_on_next_write(db, clock):
    store = Store(db, clock=clock)
    store.set("tmp", 1, ttl=5)
    clock.advance(6)
    # Expired but still on disk until a write happens (lazy expiry).
    assert "tmp" in json.loads(db.read_text())
    store.set("other", 2)
    assert json.loads(db.read_text()).keys() == {"other"}


def test_delete_expired_key_reports_false(db, clock):
    store = Store(db, clock=clock)
    store.set("tmp", 1, ttl=1)
    clock.advance(1)
    assert store.delete("tmp") is False


def test_set_resets_ttl(db, clock):
    store = Store(db, clock=clock)
    store.set("k", 1, ttl=5)
    clock.advance(4)
    store.set("k", 2)
    clock.advance(100)
    assert store.get("k") == 2


# Persistence


def test_persistence_across_instances(db, clock):
    Store(db, clock=clock).set("a", [1, 2, 3])
    Store(db, clock=clock).set("b", "x", ttl=60)
    reopened = Store(db, clock=clock)
    assert reopened.get("a") == [1, 2, 3]
    assert reopened.get("b") == "x"
    clock.advance(60)
    assert Store(db, clock=clock).get("b") is None


def test_atomic_write_leaves_no_temp_files(db):
    store = Store(db)
    for i in range(5):
        store.set(f"k{i}", i)
    leftovers = [p.name for p in db.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert json.loads(db.read_text())["k4"]["value"] == 4


def test_failed_write_keeps_previous_file(db, monkeypatch):
    store = Store(db)
    store.set("a", 1)

    def boom(*args, **kwargs):
        raise OSError("disk on fire")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.set("b", 2)
    monkeypatch.undo()
    assert Store(db).keys() == ["a"]
    assert [p for p in db.parent.iterdir() if p.name.endswith(".tmp")] == []


# Multi-process concurrency

WORKER = textwrap.dedent(
    """
    import sys
    from tinykv import Store

    path, worker, count = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    store = Store(path)
    for i in range(count):
        store.set(f"w{worker}-{i}", i)
    """
)


def test_concurrent_writers_lose_no_updates(db):
    workers, per_worker = 8, 40
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = {**os.environ, "PYTHONPATH": root + os.pathsep + os.environ.get("PYTHONPATH", "")}
    procs = [
        subprocess.Popen([sys.executable, "-c", WORKER, str(db), str(w), str(per_worker)], env=env)
        for w in range(workers)
    ]
    assert [p.wait(timeout=120) for p in procs] == [0] * workers

    store = Store(db)
    expected = {f"w{w}-{i}" for w in range(workers) for i in range(per_worker)}
    assert set(store.keys()) == expected
    assert all(store.get(f"w{w}-{i}") == i for w in range(workers) for i in range(per_worker))
