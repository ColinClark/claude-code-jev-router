"""Module-level worker for multiprocessing tests (must be top-level to be picklable)."""

from tinykv.store import Store


def increment_many(path: str, key: str, count: int) -> None:
    store = Store(path)
    for _ in range(count):
        store.update(key, lambda v: (v or 0) + 1, default=0)


def set_many(path: str, key_prefix: str, count: int, worker_id: int) -> None:
    store = Store(path)
    for i in range(count):
        store.set(f"{key_prefix}-{worker_id}-{i}", worker_id * 10_000 + i)
