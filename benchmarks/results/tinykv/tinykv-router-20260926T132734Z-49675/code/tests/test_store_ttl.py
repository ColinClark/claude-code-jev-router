"""TTL expiry using a mocked clock (no real sleeps)."""

from __future__ import annotations

import json

import pytest

import tinykv.store
from tinykv.store import Store


class FakeClock:
    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    monkeypatch.setattr(tinykv.store.time, "time", fake)
    return fake


@pytest.fixture
def path(tmp_path):
    return tmp_path / "db.json"


def test_value_available_before_expiry(clock, path):
    store = Store(path)
    store.set("k", "v", ttl=10)
    clock.advance(9.9)
    assert store.get("k") == "v"
    assert store.keys() == ["k"]


def test_value_expires_after_ttl(clock, path):
    store = Store(path)
    store.set("k", "v", ttl=10)
    clock.advance(10.5)
    assert store.get("k") is None
    assert store.get("k", "gone") == "gone"
    assert store.keys() == []


def test_expires_exactly_at_deadline(clock, path):
    store = Store(path)
    store.set("k", "v", ttl=5)
    clock.advance(5)
    assert store.get("k") is None


def test_no_ttl_never_expires(clock, path):
    store = Store(path)
    store.set("k", "v")
    clock.advance(10**9)
    assert store.get("k") == "v"


def test_reset_without_ttl_clears_expiry(clock, path):
    store = Store(path)
    store.set("k", "v", ttl=1)
    store.set("k", "v2")
    clock.advance(100)
    assert store.get("k") == "v2"


def test_expired_key_dropped_from_persisted_state_on_next_write(clock, path):
    store = Store(path)
    store.set("short", "x", ttl=1)
    store.set("long", "y", ttl=1000)
    # Expired but not yet written: still physically present in the file.
    clock.advance(2)
    assert "short" in json.loads(path.read_text())

    store.set("other", 1)

    raw = json.loads(path.read_text())
    assert "short" not in raw
    assert set(raw) == {"long", "other"}

    fresh = Store(path)
    assert sorted(fresh.keys()) == ["long", "other"]
    assert fresh.get("short") is None


def test_expired_key_dropped_on_delete(clock, path):
    store = Store(path)
    store.set("short", "x", ttl=1)
    store.set("keep", "y")
    clock.advance(2)
    store.delete("unrelated")
    assert set(json.loads(path.read_text())) == {"keep"}
