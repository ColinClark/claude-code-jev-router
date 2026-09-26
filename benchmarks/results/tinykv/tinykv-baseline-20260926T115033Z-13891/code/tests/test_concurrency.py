"""Multi-process concurrency: N writers hammer one file; every write must survive."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from conftest import ROOT

from tinykv.store import Store

WORKER = """
import sys
from tinykv.store import Store

path, worker, count = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
store = Store(path)
for i in range(count):
    store.set(f"w{worker}-{i}", {"worker": worker, "i": i})
    # Churn a key shared by all workers to maximise interleaving.
    store.set("shared", worker)
    if i % 3 == 0:
        store.delete(f"w{worker}-{i - 1}") if i else None
"""


def test_concurrent_writers_lose_no_updates(tmp_path: Path) -> None:
    db = tmp_path / "shared.json"
    workers, per_worker = 8, 40

    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", WORKER, str(db), str(w), str(per_worker)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for w in range(workers)
    ]
    for p in procs:
        _, err = p.communicate(timeout=120)
        assert p.returncode == 0, err.decode()

    store = Store(db)
    expected: set[str] = {"shared"}
    for w in range(workers):
        for i in range(per_worker):
            deleted = (i + 1) % 3 == 0 and i + 1 < per_worker  # removed by the next iteration
            if not deleted:
                expected.add(f"w{w}-{i}")
    assert set(store.keys()) == expected
    for key in expected - {"shared"}:
        w, i = (int(part) for part in key[1:].split("-"))
        assert store.get(key) == {"worker": w, "i": i}
    assert store.get("shared") in range(workers)


def test_lock_file_is_created_beside_db(tmp_path: Path) -> None:
    db = tmp_path / "x.json"
    Store(db).set("k", 1)
    assert (tmp_path / "x.json.lock").exists()
