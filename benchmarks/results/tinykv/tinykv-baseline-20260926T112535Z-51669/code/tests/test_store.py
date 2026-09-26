import json
import multiprocessing

import pytest

from tests.mp_worker import increment_many, set_many
from tinykv.store import Store


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "db.json"


class TestCrud:
    def test_set_and_get(self, db_path):
        store = Store(db_path)
        store.set("a", 1)
        assert store.get("a") == 1

    def test_set_overwrites(self, db_path):
        store = Store(db_path)
        store.set("a", 1)
        store.set("a", 2)
        assert store.get("a") == 2

    def test_get_missing_raises(self, db_path):
        store = Store(db_path)
        with pytest.raises(KeyError):
            store.get("missing")

    def test_get_missing_with_default(self, db_path):
        store = Store(db_path)
        assert store.get("missing", "fallback") == "fallback"

    def test_delete(self, db_path):
        store = Store(db_path)
        store.set("a", 1)
        store.delete("a")
        with pytest.raises(KeyError):
            store.get("a")

    def test_delete_missing_is_noop(self, db_path):
        store = Store(db_path)
        store.delete("missing")  # should not raise

    def test_keys(self, db_path):
        store = Store(db_path)
        store.set("a", 1)
        store.set("b", 2)
        assert sorted(store.keys()) == ["a", "b"]

    def test_keys_empty_store(self, db_path):
        store = Store(db_path)
        assert store.keys() == []

    def test_json_serializable_values(self, db_path):
        store = Store(db_path)
        value = {"nested": [1, 2, 3], "flag": True, "n": None}
        store.set("complex", value)
        assert store.get("complex") == value


class TestTtl:
    def test_ttl_not_yet_expired(self, db_path, monkeypatch):
        fake_time = [1000.0]
        monkeypatch.setattr("tinykv.store.time.time", lambda: fake_time[0])

        store = Store(db_path)
        store.set("a", "value", ttl=10)
        fake_time[0] += 5
        assert store.get("a") == "value"

    def test_ttl_expired_get_raises(self, db_path, monkeypatch):
        fake_time = [1000.0]
        monkeypatch.setattr("tinykv.store.time.time", lambda: fake_time[0])

        store = Store(db_path)
        store.set("a", "value", ttl=10)
        fake_time[0] += 11
        with pytest.raises(KeyError):
            store.get("a")

    def test_ttl_expired_excluded_from_keys(self, db_path, monkeypatch):
        fake_time = [1000.0]
        monkeypatch.setattr("tinykv.store.time.time", lambda: fake_time[0])

        store = Store(db_path)
        store.set("a", "value", ttl=10)
        store.set("b", "value")
        fake_time[0] += 11
        assert store.keys() == ["b"]

    def test_expired_key_dropped_on_next_write(self, db_path, monkeypatch):
        fake_time = [1000.0]
        monkeypatch.setattr("tinykv.store.time.time", lambda: fake_time[0])

        store = Store(db_path)
        store.set("a", "value", ttl=10)
        fake_time[0] += 11
        store.set("b", "other")  # triggers lazy drop of expired "a"

        raw = json.loads(db_path.read_text())
        assert "a" not in raw
        assert "b" in raw

    def test_no_ttl_never_expires(self, db_path, monkeypatch):
        fake_time = [1000.0]
        monkeypatch.setattr("tinykv.store.time.time", lambda: fake_time[0])

        store = Store(db_path)
        store.set("a", "value")
        fake_time[0] += 10_000_000
        assert store.get("a") == "value"


class TestPersistence:
    def test_persists_across_instances(self, db_path):
        Store(db_path).set("a", 42)
        assert Store(db_path).get("a") == 42

    def test_delete_persists_across_instances(self, db_path):
        Store(db_path).set("a", 1)
        Store(db_path).delete("a")
        with pytest.raises(KeyError):
            Store(db_path).get("a")

    def test_file_contains_valid_json(self, db_path):
        Store(db_path).set("a", {"x": 1})
        raw = json.loads(db_path.read_text())
        assert raw["a"]["value"] == {"x": 1}


class TestConcurrency:
    def test_concurrent_updates_no_lost_writes(self, db_path):
        store = Store(db_path)
        store.set("counter", 0)

        n_procs = 5
        n_iters = 40
        procs = [
            multiprocessing.Process(target=increment_many, args=(str(db_path), "counter", n_iters))
            for _ in range(n_procs)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
            assert p.exitcode == 0

        assert store.get("counter") == n_procs * n_iters

    def test_concurrent_distinct_key_writes_all_land(self, db_path):
        store = Store(db_path)
        n_procs = 4
        n_iters = 25
        procs = [
            multiprocessing.Process(
                target=set_many, args=(str(db_path), "k", n_iters, worker_id)
            )
            for worker_id in range(n_procs)
        ]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=30)
            assert p.exitcode == 0

        assert len(store.keys()) == n_procs * n_iters
        for worker_id in range(n_procs):
            for i in range(n_iters):
                assert store.get(f"k-{worker_id}-{i}") == worker_id * 10_000 + i
