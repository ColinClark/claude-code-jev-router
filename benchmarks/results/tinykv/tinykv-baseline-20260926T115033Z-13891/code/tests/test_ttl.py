from __future__ import annotations

import json
from pathlib import Path

from conftest import FakeClock

from tinykv.store import Store


def test_key_with_ttl_is_visible_before_expiry(store: Store, clock: FakeClock) -> None:
    store.set("k", "v", ttl=10)
    clock.advance(9.999)
    assert store.get("k") == "v"
    assert store.keys() == ["k"]


def test_key_expires_exactly_at_deadline(store: Store, clock: FakeClock) -> None:
    store.set("k", "v", ttl=10)
    clock.advance(10)
    assert store.get("k") is None
    assert store.get("k", "gone") == "gone"
    assert store.keys() == []


def test_expired_key_is_dropped_on_next_write(
    store: Store, clock: FakeClock, db_path: Path
) -> None:
    store.set("short", 1, ttl=5)
    store.set("long", 2)
    clock.advance(6)

    # Reads are lazy: the expired record is still physically on disk.
    assert "short" in json.loads(db_path.read_text())
    assert store.keys() == ["long"]

    # Any write purges expired records.
    store.set("other", 3)
    on_disk = json.loads(db_path.read_text())
    assert set(on_disk) == {"long", "other"}


def test_delete_also_purges_expired_keys(store: Store, clock: FakeClock, db_path: Path) -> None:
    store.set("short", 1, ttl=1)
    store.set("victim", 2)
    clock.advance(2)
    store.delete("victim")
    assert json.loads(db_path.read_text()) == {}


def test_deleting_expired_key_reports_false(store: Store, clock: FakeClock) -> None:
    store.set("k", 1, ttl=1)
    clock.advance(1)
    assert store.delete("k") is False


def test_overwrite_resets_or_removes_ttl(store: Store, clock: FakeClock) -> None:
    store.set("k", 1, ttl=5)
    clock.advance(4)
    store.set("k", 2, ttl=5)  # fresh deadline
    clock.advance(4)
    assert store.get("k") == 2
    store.set("k", 3)  # no ttl: never expires
    clock.advance(1_000_000)
    assert store.get("k") == 3


def test_ttl_is_persisted_as_absolute_deadline(db_path: Path, clock: FakeClock) -> None:
    Store(db_path, clock=clock).set("k", "v", ttl=30)
    assert json.loads(db_path.read_text())["k"]["expires"] == clock.now + 30

    later = FakeClock(clock.now + 31)
    assert Store(db_path, clock=later).get("k") is None
    still_early = FakeClock(clock.now + 29)
    assert Store(db_path, clock=still_early).get("k") == "v"


def test_real_clock_ttl_with_tiny_lifetime(db_path: Path) -> None:
    """One real-time check with an already-past deadline, without sleeping."""
    db_path.write_text(json.dumps({"k": {"value": 1, "expires": 1.0}}))
    assert Store(db_path).get("k") is None
    assert Store(db_path).keys() == []
