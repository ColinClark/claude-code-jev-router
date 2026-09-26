import json
import multiprocessing
import os

import pytest

from tinykv import Store


class FakeClock:
    def __init__(self, now: float = 1000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def path(tmp_path):
    return str(tmp_path / "db.json")


@pytest.fixture
def clock():
    return FakeClock()


def read_file(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- basic CRUD


def test_missing_file_is_empty_store(path):
    store = Store(path)
    assert store.get("x") is None
    assert store.get("x", "dflt") == "dflt"
    assert store.keys() == []
    assert store.delete("x") is False
    assert not os.path.exists(path)


def test_set_get_overwrite_delete(path):
    store = Store(path)
    store.set("b", {"n": [1, 2, 3]})
    store.set("a", "hello")
    assert store.get("a") == "hello"
    assert store.get("b") == {"n": [1, 2, 3]}
    assert store.keys() == ["a", "b"]

    store.set("a", 42)
    assert store.get("a") == 42

    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.get("a") is None
    assert store.keys() == ["b"]


def test_json_value_types_roundtrip(path):
    store = Store(path)
    values = {"s": "x", "i": 1, "f": 1.5, "t": True, "n": None, "l": [1, "a"], "d": {"k": 1}}
    for k, v in values.items():
        store.set(k, v)
    other = Store(path)
    for k, v in values.items():
        assert other.get(k, "missing") == v


def test_on_disk_format(path, clock):
    store = Store(path, clock=clock)
    store.set("a", 1)
    store.set("b", 2, ttl=10)
    assert read_file(path) == {
        "version": 1,
        "data": {
            "a": {"value": 1, "expires_at": None},
            "b": {"value": 2, "expires_at": 1010.0},
        },
    }


def test_sidecar_lock_file_used_and_no_temp_files_left(path):
    store = Store(path)
    store.set("a", 1)
    store.delete("a")
    directory = os.path.dirname(path)
    assert sorted(os.listdir(directory)) == ["db.json", "db.json.lock"]


def test_update(path):
    store = Store(path)
    assert store.update("n", lambda v: v + 1, default=0) == 1
    assert store.update("n", lambda v: v + 1, default=0) == 2
    assert store.get("n") == 2


def test_update_fn_error_leaves_file_untouched(path):
    store = Store(path)
    store.set("n", 1)
    before = read_file(path)

    def boom(_):
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        store.update("n", boom)
    assert read_file(path) == before


# ---------------------------------------------------------------- validation


@pytest.mark.parametrize("ttl", [0, -1, -0.5, float("nan"), float("inf")])
def test_invalid_ttl_rejected(path, ttl):
    store = Store(path)
    with pytest.raises(ValueError):
        store.set("a", 1, ttl=ttl)
    assert not os.path.exists(path)


@pytest.mark.parametrize("ttl", ["10", True])
def test_non_numeric_ttl_rejected(path, ttl):
    with pytest.raises(TypeError):
        Store(path).set("a", 1, ttl=ttl)


@pytest.mark.parametrize("value", [object(), {1, 2}, b"bytes", {"k": object()}])
def test_non_serializable_value_rejected_before_touching_file(path, value):
    store = Store(path)
    with pytest.raises((TypeError, ValueError)):
        store.set("a", value)
    assert not os.path.exists(path)

    store.set("ok", 1)
    before = read_file(path)
    with pytest.raises((TypeError, ValueError)):
        store.set("a", value)
    assert read_file(path) == before


def test_nan_value_rejected(path):
    with pytest.raises(ValueError):
        Store(path).set("a", float("nan"))
    assert not os.path.exists(path)


def test_update_non_serializable_result_rejected(path):
    store = Store(path)
    store.set("a", 1)
    before = read_file(path)
    with pytest.raises((TypeError, ValueError)):
        store.update("a", lambda _: object())
    assert read_file(path) == before


def test_non_str_key_rejected(path):
    store = Store(path)
    with pytest.raises(TypeError):
        store.set(1, "x")
    with pytest.raises(TypeError):
        store.get(1)
    with pytest.raises(TypeError):
        store.delete(1)


def test_corrupt_file_raises(path):
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"something": "else"}')
    with pytest.raises(ValueError):
        Store(path).get("a")


# ---------------------------------------------------------------- TTL


def test_ttl_expiry_with_fake_clock(path, clock):
    store = Store(path, clock=clock)
    store.set("short", "s", ttl=5)
    store.set("long", "l", ttl=100)
    store.set("forever", "f")

    clock.advance(4.999)
    assert store.get("short") == "s"
    assert store.keys() == ["forever", "long", "short"]

    clock.advance(0.001)  # exactly at expiry -> expired
    assert store.get("short") is None
    assert store.get("short", "gone") == "gone"
    assert store.keys() == ["forever", "long"]
    assert store.delete("short") is False

    clock.advance(1000)
    assert store.keys() == ["forever"]


def test_expired_entries_pruned_on_next_set(path, clock):
    store = Store(path, clock=clock)
    store.set("a", 1, ttl=1)
    store.set("b", 2, ttl=1)
    store.set("keep", 3)
    clock.advance(2)

    # Reads never rewrite the file: expired entries are still on disk.
    assert store.keys() == ["keep"]
    assert set(read_file(path)["data"]) == {"a", "b", "keep"}

    store.set("c", 4)
    assert set(read_file(path)["data"]) == {"keep", "c"}


def test_expired_entries_pruned_on_next_delete(path, clock):
    store = Store(path, clock=clock)
    store.set("a", 1, ttl=1)
    store.set("keep", 3)
    clock.advance(2)

    assert store.delete("missing") is False
    assert set(read_file(path)["data"]) == {"keep"}


def test_delete_expired_key_returns_false_and_prunes(path, clock):
    store = Store(path, clock=clock)
    store.set("a", 1, ttl=1)
    clock.advance(1)
    assert store.delete("a") is False
    assert read_file(path)["data"] == {}


def test_set_without_ttl_clears_previous_ttl(path, clock):
    store = Store(path, clock=clock)
    store.set("a", 1, ttl=1)
    store.set("a", 2)
    clock.advance(10)
    assert store.get("a") == 2


def test_update_treats_expired_as_default(path, clock):
    store = Store(path, clock=clock)
    store.set("n", 100, ttl=1)
    clock.advance(1)
    assert store.update("n", lambda v: v + 1, default=0) == 1


def test_ttl_expiry_persists_across_instances(path, clock):
    Store(path, clock=clock).set("a", 1, ttl=10)
    clock.advance(5)
    assert Store(path, clock=clock).get("a") == 1
    clock.advance(5)
    assert Store(path, clock=clock).get("a") is None


# ---------------------------------------------------------------- persistence


def test_persistence_across_instances(path):
    s1 = Store(path)
    s1.set("a", 1)
    s1.set("b", [1, 2])

    s2 = Store(path)
    assert s2.get("a") == 1
    assert s2.keys() == ["a", "b"]
    s2.delete("a")

    # No stale in-memory cache: s1 observes s2's delete.
    assert s1.get("a") is None
    assert s1.keys() == ["b"]


# ---------------------------------------------------------------- multi-process

N_PROCS = 8
N_ITERS = 50


def _worker(path: str, worker_id: int, iters: int) -> None:
    store = Store(path)
    for i in range(iters):
        store.update("counter", lambda v: v + 1, default=0)
        store.set(f"w{worker_id}-{i}", i)


def test_multiprocess_concurrency_no_lost_updates(path):
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_worker, args=(path, w, N_ITERS)) for w in range(N_PROCS)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
    for p in procs:
        assert p.exitcode == 0, f"worker exited with {p.exitcode}"

    store = Store(path)
    assert store.get("counter") == N_PROCS * N_ITERS
    expected = {f"w{w}-{i}" for w in range(N_PROCS) for i in range(N_ITERS)}
    keys = set(store.keys())
    assert expected <= keys
    assert keys == expected | {"counter"}
    assert len(keys) == N_PROCS * N_ITERS + 1
