"""Multi-process concurrency test: concurrent set()/delete() must not lose updates.

Why distinct keys rather than a get()+set() counter: ``Store.get`` does not take
the lock, so a client-side "get, then set(current + 1)" counter would lose
increments even with a perfectly correct store -- the lock only spans the
read-modify-write *inside* a single ``set``/``delete`` call. That internal cycle
is: read the whole JSON file, add/remove one key, atomically replace the whole
file. If the ``fcntl`` lock were missing or broken, two processes would read the
same snapshot and the later ``os.replace`` would silently discard the other's
key. So N processes each writing their own keys concurrently is exactly the
read-modify-write race the lock exists to prevent, and a lost key is a lost
update.
"""

import multiprocessing
from pathlib import Path

from tinykv.store import Store

NUM_PROCS = 8
SETS_PER_PROC = 50
DELETES_PER_PROC = 10  # each process deletes some of its own keys afterwards
JOIN_TIMEOUT = 60


def _worker(path: str, proc_id: int, start, n_sets: int, n_deletes: int) -> None:
    """Module-level so it is importable by ``spawn`` children."""
    store = Store(path)
    start.wait()  # maximise overlap: all workers begin writing together
    for i in range(n_sets):
        store.set(f"p{proc_id}-{i}", {"proc": proc_id, "i": i})
    for i in range(n_deletes):
        store.delete(f"p{proc_id}-{i}")


def _run_workers(path: Path, n_procs: int, n_sets: int, n_deletes: int) -> None:
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    procs = [
        ctx.Process(target=_worker, args=(str(path), pid, start, n_sets, n_deletes))
        for pid in range(n_procs)
    ]
    for p in procs:
        p.start()
    try:
        start.set()
        for p in procs:
            p.join(JOIN_TIMEOUT)
    finally:
        for p in procs:
            if p.is_alive():
                p.kill()
                p.join()
    assert [p.exitcode for p in procs] == [0] * n_procs


def test_concurrent_writers_lose_no_updates(tmp_path: Path) -> None:
    path = tmp_path / "concurrent.db.json"
    # Pre-existing data must survive the concurrent writers too.
    Store(path).set("preexisting", "keep")

    _run_workers(path, NUM_PROCS, SETS_PER_PROC, DELETES_PER_PROC)

    store = Store(path)
    expected = {
        f"p{pid}-{i}" for pid in range(NUM_PROCS) for i in range(DELETES_PER_PROC, SETS_PER_PROC)
    } | {"preexisting"}
    keys = store.keys()
    assert len(keys) == len(expected) == NUM_PROCS * (SETS_PER_PROC - DELETES_PER_PROC) + 1
    assert set(keys) == expected
    assert store.get("preexisting") == "keep"
    for pid in range(NUM_PROCS):
        for i in range(DELETES_PER_PROC, SETS_PER_PROC):
            assert store.get(f"p{pid}-{i}") == {"proc": pid, "i": i}

    # No temp files left behind by any writer.
    assert sorted(p.name for p in tmp_path.iterdir()) == [path.name, path.name + ".lock"]
