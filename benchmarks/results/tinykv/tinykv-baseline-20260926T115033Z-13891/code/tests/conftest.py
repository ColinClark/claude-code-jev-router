from __future__ import annotations

from pathlib import Path

import pytest

from tinykv.store import Store

ROOT = Path(__file__).resolve().parents[1]


class FakeClock:
    """A controllable clock so TTL tests never sleep."""

    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "data.json"


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def store(db_path: Path, clock: FakeClock) -> Store:
    return Store(db_path, clock=clock)
