import multiprocessing

from tinykv import Store

N_PROCS = 8
N_INCREMENTS = 50


def _worker(db_path: str, worker_id: int, start_event) -> None:
    """Module-level so it is importable under the "spawn" start method."""
    store = Store(db_path)
    start_event.wait()
    for i in range(N_INCREMENTS):
        store.update("counter", lambda n: n + 1, default=0)
        store.set(f"w{worker_id}:k{i}", {"worker": worker_id, "i": i})


def test_concurrent_increments_do_not_lose_updates(tmp_path):
    db_path = str(tmp_path / "db.json")
    ctx = multiprocessing.get_context("spawn")
    start_event = ctx.Event()
    procs = [
        ctx.Process(target=_worker, args=(db_path, wid, start_event)) for wid in range(N_PROCS)
    ]
    for p in procs:
        p.start()
    start_event.set()
    for p in procs:
        p.join(timeout=60)
    for p in procs:
        if p.is_alive():
            p.kill()
        assert p.exitcode == 0, f"worker exited with {p.exitcode}"

    store = Store(db_path)
    assert store.get("counter") == N_PROCS * N_INCREMENTS

    expected = {f"w{w}:k{i}" for w in range(N_PROCS) for i in range(N_INCREMENTS)}
    keys = store.keys()
    assert set(keys) == expected | {"counter"}
    assert len(keys) == len(expected) + 1
    for w in range(N_PROCS):
        for i in range(N_INCREMENTS):
            assert store.get(f"w{w}:k{i}") == {"worker": w, "i": i}

    leftovers = sorted(p.name for p in tmp_path.iterdir() if p.name.endswith(".tmp"))
    assert leftovers == []
