"""Multi-process writers to the same store file must not lose updates."""

import multiprocessing
from pathlib import Path

from tinykv.store import Store

NUM_PROCESSES = 8
WRITES_PER_PROCESS = 25
JOIN_TIMEOUT_SECONDS = 60


def _writer(db_path: str, worker_id: int, count: int) -> None:
    """Top-level (picklable) worker: write ``count`` distinct keys via its own Store."""
    store = Store(db_path)
    for i in range(count):
        store.set(f"w{worker_id}-k{i}", {"worker": worker_id, "i": i})


def _mixed_writer(db_path: str, worker_id: int, count: int) -> None:
    """Write keys, then delete every even one, exercising interleaved set/delete."""
    store = Store(db_path)
    for i in range(count):
        store.set(f"w{worker_id}-k{i}", i)
    for i in range(0, count, 2):
        store.delete(f"w{worker_id}-k{i}")


def _run_workers(target, db_path: Path) -> None:
    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(target=target, args=(str(db_path), wid, WRITES_PER_PROCESS))
        for wid in range(NUM_PROCESSES)
    ]
    for p in procs:
        p.start()
    try:
        for p in procs:
            p.join(timeout=JOIN_TIMEOUT_SECONDS)
    finally:
        for p in procs:
            if p.is_alive():
                p.kill()
                p.join()
    assert [p.exitcode for p in procs] == [0] * NUM_PROCESSES


def test_concurrent_writers_lose_no_updates(tmp_path: Path) -> None:
    db_path = tmp_path / "shared.json"
    _run_workers(_writer, db_path)

    store = Store(db_path)
    expected = {
        f"w{wid}-k{i}": {"worker": wid, "i": i}
        for wid in range(NUM_PROCESSES)
        for i in range(WRITES_PER_PROCESS)
    }
    keys = store.keys()
    assert len(keys) == NUM_PROCESSES * WRITES_PER_PROCESS
    assert set(keys) == set(expected)
    for key, value in expected.items():
        assert store.get(key) == value


def test_concurrent_set_and_delete_are_consistent(tmp_path: Path) -> None:
    db_path = tmp_path / "shared.json"
    _run_workers(_mixed_writer, db_path)

    store = Store(db_path)
    expected = {
        f"w{wid}-k{i}": i
        for wid in range(NUM_PROCESSES)
        for i in range(1, WRITES_PER_PROCESS, 2)
    }
    assert set(store.keys()) == set(expected)
    for key, value in expected.items():
        assert store.get(key) == value
