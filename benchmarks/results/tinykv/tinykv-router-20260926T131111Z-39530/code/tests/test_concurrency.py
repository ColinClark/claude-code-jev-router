import multiprocessing as mp

from tinykv import Store

PROCS = 6
ITERATIONS = 50


def _increment(n: int) -> int:
    return n + 1


def _incrementer(path: str, iterations: int) -> None:
    store = Store(path)
    for _ in range(iterations):
        store.update("counter", _increment, default=0)


def _setter(path: str, worker: int, iterations: int) -> None:
    store = Store(path)
    for i in range(iterations):
        store.set(f"w{worker}-{i}", i)


def _run(target, args_list) -> None:
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=target, args=args) for args in args_list]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=120)
        assert p.exitcode == 0


def test_concurrent_updates_lose_nothing(tmp_path):
    path = str(tmp_path / "data.json")
    _run(_incrementer, [(path, ITERATIONS)] * PROCS)
    assert Store(path).get("counter") == PROCS * ITERATIONS


def test_concurrent_distinct_key_sets_all_survive(tmp_path):
    path = str(tmp_path / "data.json")
    _run(_setter, [(path, w, ITERATIONS) for w in range(PROCS)])
    keys = Store(path).keys()
    assert len(keys) == PROCS * ITERATIONS
    assert keys == sorted(f"w{w}-{i}" for w in range(PROCS) for i in range(ITERATIONS))
