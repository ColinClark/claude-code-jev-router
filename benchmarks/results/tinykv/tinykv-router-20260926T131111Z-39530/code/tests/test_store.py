import json

import pytest

from tinykv import Store


class FakeClock:
    def __init__(self, now: float = 1000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def db(tmp_path):
    return tmp_path / "data.json"


def test_missing_file_is_empty(db):
    store = Store(db)
    assert store.get("x") is None
    assert store.get("x", 42) == 42
    assert store.keys() == []
    assert store.delete("x") is False
    assert not db.exists()


def test_crud(db):
    store = Store(db)
    store.set("b", {"n": [1, 2]})
    store.set("a", "hello")
    assert store.get("a") == "hello"
    assert store.get("b") == {"n": [1, 2]}
    assert store.keys() == ["a", "b"]
    store.set("a", 3)
    assert store.get("a") == 3
    assert store.delete("a") is True
    assert store.delete("a") is False
    assert store.get("a") is None
    assert store.keys() == ["b"]


def test_non_serializable_value_rejected(db):
    with pytest.raises(TypeError):
        Store(db).set("k", object())
    assert not db.exists()


def test_persistence_across_instances(db):
    Store(db).set("k", [1, 2, 3])
    assert Store(db).get("k") == [1, 2, 3]
    # No stale cache: a second instance sees writes by another instance.
    a, b = Store(db), Store(db)
    assert a.get("k") == [1, 2, 3]
    b.set("k", "new")
    assert a.get("k") == "new"
    assert a.keys() == ["k"]


def test_ttl_expiry(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("short", 1, ttl=10)
    store.set("forever", 2)
    assert store.get("short") == 1
    clock.now += 9.9
    assert store.keys() == ["forever", "short"]
    clock.now += 0.1
    assert store.get("short") is None
    assert store.get("short", "gone") == "gone"
    assert store.keys() == ["forever"]
    assert store.delete("short") is False


def test_expired_key_purged_on_next_write(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("tmp", 1, ttl=5)
    store.set("keep", 2)
    clock.now += 6
    # Lazy expiry: reads do not rewrite the file.
    assert store.get("tmp") is None
    assert "tmp" in json.loads(db.read_text())
    store.set("other", 3)
    assert set(json.loads(db.read_text())) == {"keep", "other"}


def test_expired_key_purged_on_delete(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("tmp", 1, ttl=5)
    store.set("keep", 2)
    clock.now += 6
    assert store.delete("missing") is False
    assert set(json.loads(db.read_text())) == {"keep"}


def test_update(db):
    store = Store(db)
    assert store.update("n", lambda v: v + 1, default=0) == 1
    assert store.update("n", lambda v: v + 1, default=0) == 2
    assert store.get("n") == 2


def test_update_preserves_ttl(db):
    clock = FakeClock()
    store = Store(db, clock=clock)
    store.set("n", 1, ttl=10)
    store.update("n", lambda v: v + 1)
    clock.now += 11
    assert store.get("n") is None


def test_atomic_write_cleans_up_temp_on_failure(db, monkeypatch):
    store = Store(db)
    store.set("k", 1)

    def boom(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr("tinykv.store.os.replace", boom)
    with pytest.raises(OSError, match="disk full"):
        store.set("k", 2)
    monkeypatch.undo()
    assert store.get("k") == 1
    assert sorted(p.name for p in db.parent.iterdir()) == ["data.json", "data.json.lock"]
