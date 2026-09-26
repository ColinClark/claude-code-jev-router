import multiprocessing

from tinykv import Store

PROCESSES = 12
KEYS_PER_PROCESS = 25


def _writer(db_path, proc_index, start_event):
    start_event.wait()
    store = Store(db_path)
    for j in range(KEYS_PER_PROCESS):
        n = proc_index * KEYS_PER_PROCESS + j
        store.set(f"key-{n}", n)


def test_concurrent_writers_lose_no_updates(tmp_path):
    # Every set() rewrites the whole file from a fresh read. Without the exclusive
    # lock around read-modify-write, two writers reading the same snapshot would each
    # drop the other's key, so any missing key here indicates a lost update.
    db = str(tmp_path / "db.json")
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    procs = [ctx.Process(target=_writer, args=(db, p, start)) for p in range(PROCESSES)]
    for proc in procs:
        proc.start()
    start.set()
    for proc in procs:
        proc.join(timeout=60)
    assert all(proc.exitcode == 0 for proc in procs)

    store = Store(db)
    expected = {f"key-{n}": n for n in range(PROCESSES * KEYS_PER_PROCESS)}
    assert sorted(store.keys()) == sorted(expected)
    for key, value in expected.items():
        assert store.get(key) == value
