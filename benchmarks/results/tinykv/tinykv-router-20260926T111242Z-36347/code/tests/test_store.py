"""Tests for tinykv.store.Store."""

from __future__ import annotations

import json
import multiprocessing as mp
import os
from pathlib import Path

import pytest

from tinykv.store import Store

N_PROCS = 8
N_ITERS = 50


class FakeClock:
    def __init__(self, now: float = 1_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "db.json"


def _on_disk(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- CRUD


def test_missing_file_is_empty_store(db_path: Path) -> None:
    store = Store(db_path)
    assert store.keys() == []
    assert store.get("nope") is None
    assert store.get("nope", 42) == 42
    assert not db_path.exists()


def test_basic_crud(db_path: Path) -> None:
    store = Store(db_path)
    store.set("b", 1)
    store.set("a", "hello")
    assert store.get("a") == "hello"
    assert store.get("b") == 1
    assert store.keys() == ["a", "b"]

    store.set("a", "overwritten")
    assert store.get("a") == "overwritten"

    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.get("a") is None
    assert store.keys() == ["b"]


@pytest.mark.parametrize(
    "value",
    [None, True, 0, -3, 1.5, "", "unicode é中", [1, "two", None], {"nested": {"x": [1, 2]}}],
)
def test_json_values_round_trip(db_path: Path, value: object) -> None:
    Store(db_path).set("k", value)
    assert Store(db_path).get("k") == value


def test_non_string_key_rejected(db_path: Path) -> None:
    store = Store(db_path)
    with pytest.raises(TypeError):
        store.set(1, "x")  # type: ignore[arg-type]


def test_unserializable_value_leaves_store_untouched(db_path: Path) -> None:
    store = Store(db_path)
    store.set("a", 1)
    with pytest.raises(TypeError):
        store.set("b", object())
    assert _on_disk(db_path) == {"a": {"value": 1, "expires_at": None}}
    assert sorted(os.listdir(db_path.parent)) == ["db.json", "db.json.lock"]


def test_update_uses_default_and_returns_new_value(db_path: Path) -> None:
    store = Store(db_path)
    assert store.update("n", lambda v: v + 1, default=0) == 1
    assert store.update("n", lambda v: v + 1, default=0) == 2
    assert store.get("n") == 2


# --------------------------------------------------------------------------- TTL


@pytest.mark.parametrize("ttl", [0, -1, -0.5, 0.0, float("nan")])
def test_non_positive_ttl_rejected(db_path: Path, ttl: float) -> None:
    store = Store(db_path)
    with pytest.raises(ValueError):
        store.set("k", "v", ttl=ttl)
    with pytest.raises(ValueError):
        store.update("k", lambda v: v, ttl=ttl)
    assert not db_path.exists()


@pytest.mark.parametrize("ttl", ["10", True])
def test_non_numeric_ttl_rejected(db_path: Path, ttl: object) -> None:
    with pytest.raises(TypeError):
        Store(db_path).set("k", "v", ttl=ttl)  # type: ignore[arg-type]


def test_ttl_expiry_with_fake_clock(db_path: Path) -> None:
    clock = FakeClock()
    store = Store(db_path, clock=clock)
    store.set("short", "s", ttl=10)
    store.set("long", "l", ttl=100.5)
    store.set("forever", "f")

    clock.advance(9.999)
    assert store.get("short") == "s"
    assert store.keys() == ["forever", "long", "short"]

    clock.advance(0.001)  # exactly at expires_at -> expired
    assert store.get("short") is None
    assert store.get("short", "dflt") == "dflt"
    assert store.keys() == ["forever", "long"]
    # Lazy expiry: reads never rewrite the file.
    assert "short" in _on_disk(db_path)

    clock.advance(1_000)
    assert store.keys() == ["forever"]


def test_expired_entries_purged_on_next_set(db_path: Path) -> None:
    clock = FakeClock()
    store = Store(db_path, clock=clock)
    store.set("a", 1, ttl=5)
    store.set("b", 2, ttl=50)
    clock.advance(6)
    assert "a" in _on_disk(db_path)

    store.set("c", 3)
    disk = _on_disk(db_path)
    assert set(disk) == {"b", "c"}
    assert disk["b"] == {"value": 2, "expires_at": 1_000.0 + 50}


def test_expired_entries_purged_on_delete(db_path: Path) -> None:
    clock = FakeClock()
    store = Store(db_path, clock=clock)
    store.set("a", 1, ttl=5)
    store.set("b", 2)
    clock.advance(10)

    # Deleting an expired key reports it as not existing, but still purges.
    assert store.delete("a") is False
    assert set(_on_disk(db_path)) == {"b"}

    store.set("c", 3, ttl=1)
    clock.advance(2)
    assert store.delete("missing") is False
    assert set(_on_disk(db_path)) == {"b"}


def test_set_resets_ttl(db_path: Path) -> None:
    clock = FakeClock()
    store = Store(db_path, clock=clock)
    store.set("k", 1, ttl=5)
    store.set("k", 2)  # no ttl -> never expires
    clock.advance(100)
    assert store.get("k") == 2


def test_update_treats_expired_as_missing(db_path: Path) -> None:
    clock = FakeClock()
    store = Store(db_path, clock=clock)
    store.set("n", 41, ttl=1)
    clock.advance(1)
    assert store.update("n", lambda v: v + 1, default=0) == 1


# --------------------------------------------------------------------------- persistence


def test_persistence_across_instances(db_path: Path) -> None:
    clock = FakeClock()
    Store(db_path, clock=clock).set("a", {"x": 1})
    Store(db_path, clock=clock).set("b", [1, 2], ttl=30)

    other = Store(db_path, clock=clock)
    assert other.keys() == ["a", "b"]
    assert other.get("a") == {"x": 1}
    assert other.delete("a") is True
    assert Store(db_path, clock=clock).keys() == ["b"]

    clock.advance(30)
    assert Store(db_path, clock=clock).keys() == []


def test_on_disk_format(db_path: Path) -> None:
    clock = FakeClock(500.0)
    store = Store(db_path, clock=clock)
    store.set("a", 1)
    store.set("b", "x", ttl=2.5)
    assert _on_disk(db_path) == {
        "a": {"value": 1, "expires_at": None},
        "b": {"value": "x", "expires_at": 502.5},
    }


def test_writes_see_changes_from_other_instances(db_path: Path) -> None:
    s1 = Store(db_path)
    s2 = Store(db_path)
    s1.set("a", 1)
    s2.set("b", 2)  # must re-read from disk, not clobber "a"
    s1.set("c", 3)
    assert Store(db_path).keys() == ["a", "b", "c"]


# --------------------------------------------------------------------------- atomic writes


def test_atomic_write_leaves_no_temp_files(db_path: Path) -> None:
    store = Store(db_path)
    for i in range(20):
        store.set(f"k{i}", i)
    store.delete("k0")
    store.update("k1", lambda v: v * 10)
    assert sorted(os.listdir(db_path.parent)) == ["db.json", "db.json.lock"]


def test_failed_replace_cleans_up_and_keeps_old_file(
    db_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = Store(db_path)
    store.set("a", 1)
    before = db_path.read_bytes()

    def boom(src: str, dst: str) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="simulated"):
        store.set("b", 2)
    monkeypatch.undo()

    assert db_path.read_bytes() == before
    assert sorted(os.listdir(db_path.parent)) == ["db.json", "db.json.lock"]


def test_failed_fsync_cleans_up(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    store = Store(db_path)
    store.set("a", 1)

    def boom(fd: int) -> None:
        raise OSError("simulated fsync failure")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(OSError, match="simulated"):
        store.set("b", 2)
    monkeypatch.undo()

    assert Store(db_path).keys() == ["a"]
    assert sorted(os.listdir(db_path.parent)) == ["db.json", "db.json.lock"]


def test_file_mode_preserved(db_path: Path) -> None:
    store = Store(db_path)
    store.set("a", 1)
    os.chmod(db_path, 0o640)
    store.set("b", 2)
    assert db_path.stat().st_mode & 0o777 == 0o640


# --------------------------------------------------------------------------- concurrency


def _increment_worker(path: str, iterations: int, barrier) -> None:
    store = Store(path)
    barrier.wait(timeout=30)
    for _ in range(iterations):
        store.update("counter", lambda v: v + 1, default=0)


def _distinct_keys_worker(path: str, worker_id: int, iterations: int, barrier) -> None:
    store = Store(path)
    barrier.wait(timeout=30)
    for i in range(iterations):
        store.set(f"w{worker_id}-{i}", [worker_id, i])


def _run_processes(target, args_for) -> None:
    ctx = mp.get_context("spawn")
    barrier = ctx.Barrier(N_PROCS)
    procs = [ctx.Process(target=target, args=(*args_for(i), barrier)) for i in range(N_PROCS)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    for p in procs:
        if p.is_alive():
            p.kill()
    assert [p.exitcode for p in procs] == [0] * N_PROCS


def test_concurrent_increments_are_not_lost(db_path: Path) -> None:
    _run_processes(_increment_worker, lambda i: (str(db_path), N_ITERS))
    store = Store(db_path)
    assert store.get("counter") == N_PROCS * N_ITERS
    assert sorted(os.listdir(db_path.parent)) == ["db.json", "db.json.lock"]


def test_concurrent_distinct_writers_all_keys_survive(db_path: Path) -> None:
    _run_processes(_distinct_keys_worker, lambda i: (str(db_path), i, N_ITERS))
    store = Store(db_path)
    expected = sorted(f"w{w}-{i}" for w in range(N_PROCS) for i in range(N_ITERS))
    assert store.keys() == expected
    assert store.get("w3-7") == [3, 7]
    assert sorted(os.listdir(db_path.parent)) == ["db.json", "db.json.lock"]
