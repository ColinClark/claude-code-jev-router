"""Multi-process test: concurrent writers must never lose an update."""

import multiprocessing as mp
import sys
import textwrap

from tinykv.store import Store

WORKERS = 8
INCREMENTS = 40


def _increment_counter(path: str, n: int, start: mp.Event) -> None:
    store = Store(path)
    start.wait()
    for _ in range(n):
        store.update("counter", lambda v: v + 1, default=0)


def _set_own_keys(path: str, worker: int, n: int, start: mp.Event) -> None:
    store = Store(path)
    start.wait()
    for i in range(n):
        store.set(f"w{worker}-{i}", worker)


def _run(target, args_for_worker, ctx):
    start = ctx.Event()
    procs = [ctx.Process(target=target, args=args_for_worker(w, start)) for w in range(WORKERS)]
    for p in procs:
        p.start()
    start.set()
    for p in procs:
        p.join(timeout=120)
    assert all(p.exitcode == 0 for p in procs), [p.exitcode for p in procs]


def test_concurrent_updates_are_not_lost(db_path):
    ctx = mp.get_context("spawn")
    path = str(db_path)
    _run(_increment_counter, lambda w, ev: (path, INCREMENTS, ev), ctx)
    assert Store(path).get("counter") == WORKERS * INCREMENTS


def test_concurrent_sets_of_distinct_keys_are_not_lost(db_path):
    ctx = mp.get_context("spawn")
    path = str(db_path)
    _run(_set_own_keys, lambda w, ev: (path, w, INCREMENTS, ev), ctx)
    store = Store(path)
    assert len(store.keys()) == WORKERS * INCREMENTS
    for w in range(WORKERS):
        for i in range(INCREMENTS):
            assert store.get(f"w{w}-{i}") == w


def test_lock_serializes_independent_interpreters(db_path, tmp_path):
    """Belt and braces: separate `python` subprocesses, not multiprocessing."""
    import subprocess

    script = tmp_path / "worker.py"
    script.write_text(
        textwrap.dedent(
            """
            import sys
            from tinykv.store import Store
            path, n = sys.argv[1], int(sys.argv[2])
            s = Store(path)
            for _ in range(n):
                s.update("hits", lambda v: v + 1, default=0)
            """
        )
    )
    procs = [
        subprocess.Popen([sys.executable, str(script), str(db_path), str(INCREMENTS)])
        for _ in range(WORKERS)
    ]
    assert [p.wait(timeout=120) for p in procs] == [0] * WORKERS
    assert Store(db_path).get("hits") == WORKERS * INCREMENTS
