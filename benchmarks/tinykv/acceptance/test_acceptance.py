"""Hidden acceptance tests for the tinykv benchmark, written only from benchmarks/tinykv/prompt.md.

Neither mode sees these tests. benchmarks/grade.sh runs them against each run's generated code, so both
modes are judged by the same yardstick instead of by the tests each run wrote for itself.
"""

import json
import multiprocessing as mp
import subprocess
import sys
import time
from pathlib import Path

import pytest
from tinykv.store import Store

WRITERS = 4
KEYS_PER_WRITER = 40


def _writer(db: str, worker: int) -> None:
    store = Store(db)
    for i in range(KEYS_PER_WRITER):
        store.set(f"w{worker}-k{i}", {"worker": worker, "i": i})


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "store.json")


def absent(store, key) -> bool:
    """The prompt only says missing/expired keys are "never returned": accept get() -> None or KeyError."""
    try:
        return store.get(key) is None
    except KeyError:
        return True


def test_crud_roundtrip(db):
    s = Store(db)
    s.set("a", 1)
    s.set("b", {"nested": [1, 2, 3]})
    assert s.get("a") == 1
    assert s.get("b") == {"nested": [1, 2, 3]}
    s.set("a", "updated")
    assert s.get("a") == "updated"
    s.delete("a")
    assert absent(s, "a")
    assert sorted(s.keys()) == ["b"]


def test_missing_key_is_not_returned(db):
    assert absent(Store(db), "nope")


def test_persistence_across_instances(db):
    Store(db).set("persist", [1, "two"])
    assert Store(db).get("persist") == [1, "two"]


def test_ttl_expiry(db):
    s = Store(db)
    s.set("short", "gone soon", ttl=1)
    s.set("long", "stays", ttl=60)
    s.set("forever", "no ttl")
    assert s.get("short") == "gone soon"
    time.sleep(1.2)
    assert absent(s, "short")
    assert "short" not in list(s.keys())
    assert sorted(s.keys()) == ["forever", "long"]
    assert absent(Store(db), "short")  # also expired for a fresh instance


def test_expired_keys_dropped_on_next_write(db):
    s = Store(db)
    s.set("zz-expiring-marker", "x", ttl=1)
    time.sleep(1.2)
    s.set("other", 1)
    assert "zz-expiring-marker" not in Path(db).read_text()


def test_atomic_writes_leave_no_temp_files(db):
    s = Store(db)
    for i in range(20):
        s.set(f"k{i}", i)
    leftovers = [p.name for p in Path(db).parent.iterdir() if "tmp" in p.name.lower() or p.suffix == ".tmp"]
    assert leftovers == []
    json.loads(Path(db).read_text())  # the data file is complete, valid JSON


def test_concurrent_writers_lose_no_updates(db):
    ctx = mp.get_context("spawn")
    procs = [ctx.Process(target=_writer, args=(db, w)) for w in range(WRITERS)]
    for p in procs:
        p.start()
    for p in procs:
        p.join(60)
        assert p.exitcode == 0
    keys = set(Store(db).keys())
    assert len(keys) == WRITERS * KEYS_PER_WRITER


def cli(db, *args):
    return subprocess.run(
        [sys.executable, "-m", "tinykv", "--db", db, *args], capture_output=True, text=True, timeout=30
    )


def test_cli_set_get_del_keys(db):
    assert cli(db, "set", "greeting", "hello").returncode == 0
    got = cli(db, "get", "greeting")
    assert got.returncode == 0 and "hello" in got.stdout
    listed = cli(db, "keys")
    assert listed.returncode == 0 and "greeting" in listed.stdout
    assert cli(db, "del", "greeting").returncode == 0
    assert cli(db, "get", "greeting").returncode == 1


def test_cli_missing_key_exits_1(db):
    assert cli(db, "get", "never-set").returncode == 1


def test_cli_ttl(db):
    assert cli(db, "set", "temp", "v", "--ttl", "1").returncode == 0
    assert cli(db, "get", "temp").returncode == 0
    time.sleep(1.2)
    assert cli(db, "get", "temp").returncode == 1
