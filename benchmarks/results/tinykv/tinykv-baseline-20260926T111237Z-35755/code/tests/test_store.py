import json
import multiprocessing as mp

import pytest

from tinykv import Store


class FakeClock:
    def __init__(self, t: float = 1_000_000.0):
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


@pytest.fixture
def db(tmp_path):
    return tmp_path / "test.db.json"


# -- CRUD ---------------------------------------------------------------------


def test_get_missing_returns_default(db):
    s = Store(db)
    assert s.get("nope") is None
    assert s.get("nope", 7) == 7
    assert s.keys() == []


def test_set_get_overwrite(db):
    s = Store(db)
    s.set("a", 1)
    s.set("b", {"nested": [1, 2, None]})
    assert s.get("a") == 1
    assert s.get("b") == {"nested": [1, 2, None]}
    s.set("a", "two")
    assert s.get("a") == "two"
    assert s.keys() == ["a", "b"]


def test_delete(db):
    s = Store(db)
    s.set("a", 1)
    assert s.delete("a") is True
    assert s.get("a") is None
    assert s.delete("a") is False
    assert "a" not in s


def test_stored_falsy_values_are_distinguishable(db):
    s = Store(db)
    s.set("n", None)
    s.set("z", 0)
    assert "n" in s and s.get("n", "default") is None
    assert s.get("z") == 0


def test_non_serializable_value_rejected_without_writing(db):
    s = Store(db)
    with pytest.raises(TypeError):
        s.set("x", object())
    assert not db.exists()


# -- TTL ----------------------------------------------------------------------


def test_ttl_expiry_with_fake_clock(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("temp", "v", ttl=10)
    s.set("perm", "p")
    clock.advance(9.999)
    assert s.get("temp") == "v"
    assert s.keys() == ["perm", "temp"]
    clock.advance(0.001)
    assert s.get("temp") is None
    assert "temp" not in s
    assert s.keys() == ["perm"]


def test_expired_key_dropped_on_next_write(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("temp", "v", ttl=5)
    clock.advance(6)
    # Lazy: still on disk until a write happens.
    assert "temp" in json.loads(db.read_text())
    s.set("other", 1)
    assert "temp" not in json.loads(db.read_text())


def test_delete_expired_key_reports_false(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("temp", "v", ttl=1)
    clock.advance(2)
    assert s.delete("temp") is False


def test_set_without_ttl_clears_previous_ttl(db):
    clock = FakeClock()
    s = Store(db, clock=clock)
    s.set("k", 1, ttl=1)
    s.set("k", 2)
    clock.advance(100)
    assert s.get("k") == 2


@pytest.mark.parametrize("ttl", [0, -1])
def test_invalid_ttl(db, ttl):
    with pytest.raises(ValueError):
        Store(db).set("k", 1, ttl=ttl)


# -- persistence --------------------------------------------------------------


def test_persistence_across_instances(db):
    Store(db).set("a", [1, 2, 3])
    Store(db).set("b", True)
    s = Store(db)
    assert s.get("a") == [1, 2, 3]
    assert s.get("b") is True
    assert s.keys() == ["a", "b"]


def test_ttl_persists_across_instances(db):
    clock = FakeClock()
    Store(db, clock=clock).set("t", 1, ttl=5)
    clock.advance(5)
    assert Store(db, clock=clock).get("t") is None


def test_atomic_write_leaves_no_temp_files(db):
    s = Store(db)
    for i in range(5):
        s.set(f"k{i}", i)
    leftovers = [p.name for p in db.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []
    assert json.loads(db.read_text())["k4"]["v"] == 4


def test_failed_write_keeps_previous_file(db, monkeypatch):
    s = Store(db)
    s.set("a", 1)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("tinykv.store.os.replace", boom)
    with pytest.raises(OSError):
        s.set("a", 2)
    monkeypatch.undo()
    assert Store(db).get("a") == 1
    assert not [p for p in db.parent.iterdir() if p.name.endswith(".tmp")]


# -- concurrency --------------------------------------------------------------


def _incrementer(path: str, n: int, start) -> None:
    start.wait()
    s = Store(path)
    for i in range(n):
        # Read-modify-write of a shared counter through the store's locked write path,
        # plus a unique key per write so both lost-update modes are detectable.
        with s._write() as (data, _now):
            entry = data.get("counter")
            data["counter"] = {"v": (entry["v"] if entry else 0) + 1, "e": None}
        s.set(f"{mp.current_process().name}-{i}", i)


def test_concurrent_writers_lose_no_updates(db):
    procs_n, per_proc = 8, 50
    ctx = mp.get_context("spawn")
    start = ctx.Event()
    procs = [
        ctx.Process(target=_incrementer, args=(str(db), per_proc, start), name=f"w{p}")
        for p in range(procs_n)
    ]
    for p in procs:
        p.start()
    start.set()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0
    s = Store(db)
    assert s.get("counter") == procs_n * per_proc
    assert len(s.keys()) == procs_n * per_proc + 1
