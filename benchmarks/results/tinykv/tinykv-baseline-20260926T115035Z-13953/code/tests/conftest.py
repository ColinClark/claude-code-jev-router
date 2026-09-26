import pytest

from tinykv.store import Store


class FakeClock:
    """A controllable clock so TTL tests never sleep."""

    def __init__(self, now: float = 1_000_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db.json"


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(db_path, clock):
    return Store(db_path, clock=clock)
