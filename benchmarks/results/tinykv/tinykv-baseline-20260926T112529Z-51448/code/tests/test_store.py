import json
import time

import pytest

from tinykv.store import Store


def test_set_get_basic(tmp_path):
    store = Store(tmp_path / "db.json")
    store.set("a", 1)
    store.set("b", {"x": [1, 2, 3]})
    assert store.get("a") == 1
    assert store.get("b") == {"x": [1, 2, 3]}


def test_get_missing_key_returns_none(tmp_path):
    store = Store(tmp_path / "db.json")
    assert store.get("missing") is None


def test_overwrite_key(tmp_path):
    store = Store(tmp_path / "db.json")
    store.set("a", 1)
    store.set("a", 2)
    assert store.get("a") == 2


def test_delete(tmp_path):
    store = Store(tmp_path / "db.json")
    store.set("a", 1)
    assert store.delete("a") is True
    assert store.get("a") is None
    assert store.delete("a") is False


def test_keys(tmp_path):
    store = Store(tmp_path / "db.json")
    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)
    assert sorted(store.keys()) == ["a", "b", "c"]


def test_ttl_expiry_using_manual_clock(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.json")
    fake_now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])

    store.set("a", "value", ttl=10)
    assert store.get("a") == "value"

    fake_now[0] += 11
    assert store.get("a") is None
    assert "a" not in store.keys()


def test_ttl_dropped_on_next_write(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.json")
    fake_now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])

    store.set("a", "value", ttl=10)
    fake_now[0] += 11

    raw_before = json.loads((tmp_path / "db.json").read_text())
    assert "a" in raw_before

    store.set("b", "other")

    raw_after = json.loads((tmp_path / "db.json").read_text())
    assert "a" not in raw_after
    assert "b" in raw_after


def test_no_ttl_never_expires(tmp_path, monkeypatch):
    store = Store(tmp_path / "db.json")
    fake_now = [1000.0]
    monkeypatch.setattr(time, "time", lambda: fake_now[0])

    store.set("a", "value")
    fake_now[0] += 10_000
    assert store.get("a") == "value"


def test_persistence_across_instances(tmp_path):
    db_path = tmp_path / "db.json"
    store1 = Store(db_path)
    store1.set("a", "hello")

    store2 = Store(db_path)
    assert store2.get("a") == "hello"


def _concurrent_write_worker(path, proc_id, n):
    s = Store(path)
    for i in range(n):
        s.set(f"p{proc_id}_k{i}", proc_id * 1000 + i)


def test_persistence_survives_new_process(tmp_path):
    import subprocess
    import sys

    db_path = tmp_path / "db.json"
    subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", str(db_path), "set", "k", '"v"'],
        check=True,
    )
    store = Store(db_path)
    assert store.get("k") == "v"


@pytest.mark.parametrize("n_procs", [8])
def test_concurrent_writers_no_lost_updates(tmp_path, n_procs):
    """Spawn multiple processes each writing many distinct keys via the public API.

    Each Store.set() performs a full read-modify-write of the whole JSON
    document. If the exclusive lock around that cycle didn't work, concurrent
    writers would clobber each other's keys and some writes would be lost.
    """
    import multiprocessing

    db_path = tmp_path / "db.json"
    writes_per_proc = 15

    ctx = multiprocessing.get_context("spawn")
    procs = [
        ctx.Process(target=_concurrent_write_worker, args=(db_path, proc_id, writes_per_proc))
        for proc_id in range(n_procs)
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join(timeout=60)
        assert p.exitcode == 0

    store = Store(db_path)
    all_keys = set(store.keys())
    expected_keys = {
        f"p{proc_id}_k{i}" for proc_id in range(n_procs) for i in range(writes_per_proc)
    }
    assert all_keys == expected_keys
    for proc_id in range(n_procs):
        for i in range(writes_per_proc):
            assert store.get(f"p{proc_id}_k{i}") == proc_id * 1000 + i
