"""Shared fixtures for the tinykv test suite."""

import time
from pathlib import Path

import pytest

from tinykv.store import Store


class FakeClock:
    """Stand-in for the ``time`` module inside ``tinykv.store`` with a controllable clock."""

    def __init__(self, start: float) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    """Replace the ``time`` module referenced by ``tinykv.store`` with a fake clock.

    Only ``tinykv.store``'s view of time is patched, so pytest and the rest of the
    process keep using the real clock.
    """
    fake = FakeClock(start=time.time())
    monkeypatch.setattr("tinykv.store.time", fake)
    return fake


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "db.json"


@pytest.fixture
def store(db_path: Path) -> Store:
    return Store(db_path)
