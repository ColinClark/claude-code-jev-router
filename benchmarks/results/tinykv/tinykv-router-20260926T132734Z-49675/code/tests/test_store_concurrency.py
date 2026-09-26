"""Cross-process concurrency: no lost updates under real multiprocessing contention."""

from __future__ import annotations

import multiprocessing

from tinykv.store import Store

NUM_WORKERS = 8
WRITES_PER_WORKER = 30


def _worker(path: str, worker_id: int, start) -> None:
    # Module-level so it is picklable under the "spawn" start method (macOS default).
    start.wait()
    for i in range(WRITES_PER_WORKER):
        Store(path).set(f"key-{worker_id}-{i}", i)


def test_concurrent_writers_lose_no_updates(tmp_path):
    path = str(tmp_path / "db.json")
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    procs = [
        ctx.Process(target=_worker, args=(path, worker_id, start))
        for worker_id in range(NUM_WORKERS)
    ]
    for p in procs:
        p.start()
    start.set()  # release all workers together to maximize contention
    for p in procs:
        p.join(timeout=120)

    for p in procs:
        assert not p.is_alive(), "worker process hung"
        assert p.exitcode == 0, f"worker exited with {p.exitcode}"

    store = Store(path)
    expected = {
        f"key-{w}-{i}": i for w in range(NUM_WORKERS) for i in range(WRITES_PER_WORKER)
    }
    keys = store.keys()
    missing = sorted(set(expected) - set(keys))
    assert not missing, f"{len(missing)} lost updates, e.g. {missing[:5]}"
    assert len(keys) == len(expected)
    for key, value in expected.items():
        assert store.get(key) == value
