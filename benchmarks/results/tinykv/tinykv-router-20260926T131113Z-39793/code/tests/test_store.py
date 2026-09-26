import json
import multiprocessing
import os

import pytest

from tinykv import Store


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "store.db.json")


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------- CRUD
def test_missing_file_is_empty(db):
    s = Store(db)
    assert s.get("x") is None
    assert s.get("x", "dflt") == "dflt"
    assert s.keys() == []
    assert s.delete("x") is False


def test_empty_file_is_empty(db):
    open(db, "w").close()
    assert Store(db).keys() == []


def test_basic_crud(db):
    s = Store(db)
    s.set("a", 1)
    s.set("b", {"nested": [1, 2, "x"]})
    s.set("c", "text")
    assert s.get("a") == 1
    assert s.get("b") == {"nested": [1, 2, "x"]}
    assert s.get("c") == "text"
    assert sorted(s.keys()) == ["a", "b", "c"]

    s.set("a", 2)
    assert s.get("a") == 2

    assert s.delete("a") is True
    assert s.delete("a") is False
    assert s.get("a") is None
    assert sorted(s.keys()) == ["b", "c"]


def test_falsy_values_distinguished_from_missing(db):
    s = Store(db)
    s.set("n", None)
    s.set("z", 0)
    assert s.get("n", "dflt") is None
    assert s.get("z", "dflt") == 0


def test_non_serializable_value_rejected(db):
    s = Store(db)
    with pytest.raises(TypeError):
        s.set("x", object())
    assert not os.path.exists(db)


def test_update(db):
    s = Store(db)
    assert s.update("n", lambda v: v + 1, default=0) == 1
    assert s.update("n", lambda v: v + 1, default=0) == 2
    assert s.get("n") == 2


# -------------------------------------------------------------- persistence
def test_persistence_across_instances(db):
    Store(db).set("k", [1, 2, 3])
    Store(db).set("j", "v")
    s = Store(db)
    assert s.get("k") == [1, 2, 3]
    assert sorted(s.keys()) == ["j", "k"]


def test_no_stale_cache_between_instances(db):
    a, b = Store(db), Store(db)
    a.set("k", 1)
    assert b.get("k") == 1
    b.set("k", 2)
    assert a.get("k") == 2


def test_atomic_write_leaves_no_temp_files(db, tmp_path):
    s = Store(db)
    for i in range(5):
        s.set(f"k{i}", i)
    leftovers = [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_failed_write_cleans_up_temp(db, tmp_path, monkeypatch):
    s = Store(db)
    s.set("keep", 1)

    def boom(src, dst):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        s.set("new", 2)
    monkeypatch.undo()

    assert [p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp")] == []
    assert Store(db).get("keep") == 1
    assert Store(db).get("new") is None


# ---------------------------------------------------------------------- TTL
def test_ttl_expiry_with_fake_clock(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("short", "v", ttl=10)
    s.set("forever", "v")
    assert s.get("short") == "v"
    clock.advance(9.9)
    assert s.get("short") == "v"
    clock.advance(0.2)
    assert s.get("short") is None
    assert s.get("short", "gone") == "gone"
    assert s.keys() == ["forever"]
    assert s.delete("short") is False


def test_expired_entry_purged_on_next_write(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("short", "v", ttl=5)
    assert "short" in read_file(db)

    clock.advance(6)
    # Lazy expiry: reading does not rewrite the file.
    assert s.get("short") is None
    assert "short" in read_file(db)

    s.set("other", 1)
    assert "short" not in read_file(db)
    assert set(read_file(db)) == {"other"}


def test_set_overwrite_clears_ttl(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("k", 1, ttl=5)
    s.set("k", 2)
    clock.advance(100)
    assert s.get("k") == 2


def test_update_on_expired_key_uses_default(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("n", 41, ttl=1)
    clock.advance(2)
    assert s.update("n", lambda v: v + 1, default=0) == 1


def test_invalid_ttl(db):
    with pytest.raises(ValueError):
        Store(db).set("k", 1, ttl=0)


# ------------------------------------------------------------- concurrency
def _increment(v):
    return v + 1


def _worker(path: str, n: int) -> None:
    s = Store(path)
    for _ in range(n):
        s.update("counter", _increment, default=0)


def test_multiprocess_increments_not_lost(db):
    procs, n = 6, 50
    ctx = multiprocessing.get_context("spawn")
    workers = [ctx.Process(target=_worker, args=(db, n)) for _ in range(procs)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=120)
    assert all(w.exitcode == 0 for w in workers)
    assert Store(db).get("counter") == procs * n
