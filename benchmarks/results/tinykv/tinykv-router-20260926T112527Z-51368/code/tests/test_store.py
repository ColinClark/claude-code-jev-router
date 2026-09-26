"""Tests for tinykv.store.Store: CRUD, TTL expiry and persistence."""

import gc
import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from tinykv.store import Store


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "store.db.json"


@pytest.fixture
def store(db_path: Path) -> Store:
    return Store(db_path)


class FakeClock:
    """Deterministic replacement for ``time.time`` used inside tinykv.store."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock():
    fake = FakeClock()
    with patch("tinykv.store.time.time", fake):
        yield fake


def raw_records(path: Path) -> dict:
    """Return the on-disk JSON content, bypassing Store (no expiry filtering)."""
    return json.loads(path.read_text(encoding="utf-8"))


# -- basic CRUD ---------------------------------------------------------------


def test_set_get_round_trip(store: Store) -> None:
    store.set("a", "hello")
    assert store.get("a") == "hello"


def test_set_overwrites_existing_value(store: Store) -> None:
    store.set("a", 1)
    store.set("a", 2)
    assert store.get("a") == 2
    assert store.keys() == ["a"]


def test_delete_removes_key(store: Store) -> None:
    store.set("a", 1)
    store.set("b", 2)
    store.delete("a")
    with pytest.raises(KeyError):
        store.get("a")
    assert store.get("b") == 2
    assert store.keys() == ["b"]


def test_get_missing_key_raises_key_error(store: Store) -> None:
    with pytest.raises(KeyError):
        store.get("nope")
    store.set("other", 1)
    with pytest.raises(KeyError):
        store.get("nope")


def test_delete_missing_key_raises_key_error(store: Store) -> None:
    with pytest.raises(KeyError):
        store.delete("nope")
    store.set("a", 1)
    store.delete("a")
    with pytest.raises(KeyError):
        store.delete("a")


def test_keys_reflects_current_state(store: Store) -> None:
    assert store.keys() == []
    store.set("a", 1)
    store.set("b", 2)
    store.set("c", 3)
    assert sorted(store.keys()) == ["a", "b", "c"]
    store.delete("b")
    assert sorted(store.keys()) == ["a", "c"]
    store.set("a", 10)  # overwrite does not duplicate
    assert sorted(store.keys()) == ["a", "c"]
    store.delete("a")
    store.delete("c")
    assert store.keys() == []


@pytest.mark.parametrize(
    "value",
    [
        {"nested": {"x": [1, 2, {"y": None}]}, "flag": True},
        [1, "two", 3.5, None, False, [], {}],
        "a string with unicode é☃",
        "",
        0,
        -42,
        12345678901234567890,
        3.14159,
        True,
        False,
        None,
        {},
        [],
    ],
    ids=lambda v: type(v).__name__ + ":" + repr(v)[:20],
)
def test_json_value_types_round_trip(store: Store, db_path: Path, value: object) -> None:
    store.set("k", value)
    got = store.get("k")
    assert got == value
    assert type(got) is type(value)
    # And a fresh instance reading from disk sees the same thing.
    assert Store(db_path).get("k") == value


def test_none_value_is_distinct_from_missing(store: Store) -> None:
    store.set("k", None)
    assert store.get("k") is None
    assert store.keys() == ["k"]


# -- TTL expiry (deterministic fake clock, no sleeps) ---------------------------


def test_key_is_live_before_ttl_and_expired_at_ttl(store: Store, clock: FakeClock) -> None:
    store.set("k", "v", ttl=10)
    clock.advance(9.999)
    assert store.get("k") == "v"
    assert store.keys() == ["k"]
    clock.advance(0.001)  # exactly at expires_at: expiry uses `now >= expires_at`
    with pytest.raises(KeyError):
        store.get("k")
    assert store.keys() == []


def test_expired_key_delete_raises_key_error(store: Store, clock: FakeClock) -> None:
    store.set("k", "v", ttl=5)
    clock.advance(6)
    with pytest.raises(KeyError):
        store.delete("k")


def test_ttl_none_never_expires(store: Store, clock: FakeClock) -> None:
    store.set("forever", 1)
    store.set("explicit_none", 2, ttl=None)
    clock.advance(10**9)  # ~31 years
    assert store.get("forever") == 1
    assert store.get("explicit_none") == 2
    assert sorted(store.keys()) == ["explicit_none", "forever"]


def test_resetting_key_without_ttl_clears_expiry(store: Store, clock: FakeClock) -> None:
    store.set("k", "old", ttl=5)
    store.set("k", "new")
    clock.advance(100)
    assert store.get("k") == "new"


def test_resetting_key_with_new_ttl_extends_expiry(store: Store, clock: FakeClock) -> None:
    store.set("k", "v", ttl=5)
    clock.advance(4)
    store.set("k", "v", ttl=5)  # expires at start + 9 now
    clock.advance(4)
    assert store.get("k") == "v"
    clock.advance(1)
    with pytest.raises(KeyError):
        store.get("k")


def test_expires_at_is_absolute_timestamp_on_disk(
    store: Store, db_path: Path, clock: FakeClock
) -> None:
    store.set("ttl", 1, ttl=30)
    store.set("no_ttl", 2)
    records = raw_records(db_path)
    assert records["ttl"] == {"value": 1, "expires_at": clock.now + 30}
    assert records["no_ttl"] == {"value": 2, "expires_at": None}


def test_expiry_is_lazy_and_purged_on_next_set(
    store: Store, db_path: Path, clock: FakeClock
) -> None:
    store.set("short", "s", ttl=10)
    store.set("long", "l", ttl=1000)
    clock.advance(11)

    # Logically gone...
    with pytest.raises(KeyError):
        store.get("short")
    assert store.keys() == ["long"]
    # ...but reads never write, so the record is still physically on disk.
    assert "short" in raw_records(db_path)

    # The next write purges it.
    store.set("other", "o")
    records = raw_records(db_path)
    assert "short" not in records
    assert set(records) == {"long", "other"}


def test_expiry_is_purged_on_next_delete(store: Store, db_path: Path, clock: FakeClock) -> None:
    store.set("short", "s", ttl=10)
    store.set("keep", 1)
    store.set("victim", 2)
    clock.advance(11)
    assert "short" in raw_records(db_path)

    store.delete("victim")
    records = raw_records(db_path)
    assert set(records) == {"keep"}


def test_expiry_is_purged_even_when_delete_raises(
    store: Store, db_path: Path, clock: FakeClock
) -> None:
    store.set("short", "s", ttl=10)
    store.set("keep", 1)
    clock.advance(11)
    assert "short" in raw_records(db_path)

    with pytest.raises(KeyError):
        store.delete("missing")
    assert set(raw_records(db_path)) == {"keep"}


def test_expiry_with_real_clock(store: Store) -> None:
    # One real-time sanity check that the un-mocked clock path works too.
    # Kept deliberately tiny; all other TTL tests use the fake clock.
    store.set("k", "v", ttl=0.05)
    time.sleep(0.1)
    with pytest.raises(KeyError):
        store.get("k")


@pytest.mark.parametrize("bad_ttl", ["10", True, [1]])
def test_non_numeric_ttl_rejected(store: Store, db_path: Path, bad_ttl: object) -> None:
    with pytest.raises(TypeError):
        store.set("k", "v", ttl=bad_ttl)  # type: ignore[arg-type]
    assert not db_path.exists()


# -- persistence across instances ----------------------------------------------


def test_data_persists_across_instances(db_path: Path) -> None:
    first = Store(db_path)
    first.set("a", {"x": 1})
    first.set("b", [1, 2, 3])
    first.set("c", "gone")
    first.delete("c")
    del first
    gc.collect()

    second = Store(db_path)
    assert second.get("a") == {"x": 1}
    assert second.get("b") == [1, 2, 3]
    with pytest.raises(KeyError):
        second.get("c")
    assert sorted(second.keys()) == ["a", "b"]


def test_instances_do_not_cache(db_path: Path) -> None:
    one = Store(db_path)
    two = Store(db_path)

    one.set("k", 1)
    assert two.get("k") == 1

    two.set("k", 2)
    assert one.get("k") == 2

    two.delete("k")
    with pytest.raises(KeyError):
        one.get("k")
    assert one.keys() == []

    one.set("new", "n")
    assert two.keys() == ["new"]


def test_ttl_persists_across_instances(db_path: Path, clock: FakeClock) -> None:
    Store(db_path).set("k", "v", ttl=10)
    assert Store(db_path).get("k") == "v"
    clock.advance(10)
    with pytest.raises(KeyError):
        Store(db_path).get("k")


def test_missing_and_empty_file_are_empty_store(db_path: Path) -> None:
    assert Store(db_path).keys() == []
    db_path.write_text("", encoding="utf-8")
    assert Store(db_path).keys() == []
    with pytest.raises(KeyError):
        Store(db_path).get("k")


def test_no_temp_files_left_behind(db_path: Path) -> None:
    s = Store(db_path)
    for i in range(5):
        s.set(f"k{i}", i)
    s.delete("k0")
    leftovers = sorted(p.name for p in db_path.parent.iterdir())
    assert leftovers == [db_path.name, db_path.name + ".lock"]
