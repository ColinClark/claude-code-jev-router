"""TTL expiry, driven by a fake clock patched into tinykv.store (no real sleeps)."""

import json
import time
from pathlib import Path

from tinykv.store import Store

from .conftest import FakeClock


def _on_disk(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_key_with_ttl_is_available_before_expiry(store: Store, clock: FakeClock) -> None:
    store.set("k", "v", ttl=10)
    assert store.get("k") == "v"
    assert store.keys() == ["k"]
    clock.advance(9.999)
    assert store.get("k") == "v"
    assert store.keys() == ["k"]


def test_expiry_timestamp_is_absolute(store: Store, db_path: Path, clock: FakeClock) -> None:
    start = clock.now
    store.set("k", "v", ttl=10)
    assert _on_disk(db_path)["k"]["expires_at"] == start + 10


def test_get_returns_none_after_expiry(store: Store, clock: FakeClock) -> None:
    store.set("k", "v", ttl=10)
    clock.advance(10)  # expiry is inclusive: expires_at <= now
    assert store.get("k") is None
    clock.advance(1000)
    assert store.get("k") is None


def test_keys_excludes_expired(store: Store, clock: FakeClock) -> None:
    store.set("short", 1, ttl=5)
    store.set("long", 2, ttl=50)
    store.set("forever", 3)
    assert sorted(store.keys()) == ["forever", "long", "short"]
    clock.advance(6)
    assert sorted(store.keys()) == ["forever", "long"]
    clock.advance(50)
    assert store.keys() == ["forever"]


def test_expiry_is_lazy_until_next_write(store: Store, db_path: Path, clock: FakeClock) -> None:
    store.set("k", "v", ttl=1)
    clock.advance(2)
    # Reads never write, so the expired entry is still physically present.
    assert store.get("k") is None
    assert store.keys() == []
    assert "k" in _on_disk(db_path)


def test_expired_key_swept_from_disk_on_next_set(
    store: Store, db_path: Path, clock: FakeClock
) -> None:
    store.set("k", "v", ttl=1)
    store.set("keep", "x")
    clock.advance(2)
    store.set("other", "y")
    data = _on_disk(db_path)
    assert "k" not in data
    assert set(data) == {"keep", "other"}


def test_expired_key_swept_from_disk_on_next_delete(
    store: Store, db_path: Path, clock: FakeClock
) -> None:
    store.set("k", "v", ttl=1)
    store.set("keep", "x")
    clock.advance(2)
    store.delete("unrelated-missing-key")
    data = _on_disk(db_path)
    assert "k" not in data
    assert set(data) == {"keep"}


def test_unexpired_ttl_key_survives_sweep(store: Store, db_path: Path, clock: FakeClock) -> None:
    store.set("soon", 1, ttl=1)
    store.set("later", 2, ttl=100)
    clock.advance(2)
    store.set("trigger", 3)
    data = _on_disk(db_path)
    assert set(data) == {"later", "trigger"}
    assert store.get("later") == 2


def test_ttl_none_never_expires(store: Store, db_path: Path, clock: FakeClock) -> None:
    store.set("k", "v", ttl=None)
    assert _on_disk(db_path)["k"]["expires_at"] is None
    clock.advance(100 * 365 * 24 * 3600)  # a century later
    assert store.get("k") == "v"
    assert store.keys() == ["k"]
    store.set("trigger", 1)  # sweep must not remove it either
    assert "k" in _on_disk(db_path)
    assert store.get("k") == "v"


def test_reset_with_ttl_none_clears_expiry(store: Store, clock: FakeClock) -> None:
    store.set("k", "v1", ttl=1)
    store.set("k", "v2")
    clock.advance(10)
    assert store.get("k") == "v2"


def test_real_sleep_sanity_check(store: Store) -> None:
    """One small real-clock check that the unpatched path expires too."""
    store.set("k", "v", ttl=0.05)
    assert store.get("k") == "v"
    time.sleep(0.1)
    assert store.get("k") is None
    assert store.keys() == []
