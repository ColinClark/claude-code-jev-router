"""Import path setup, plus a per-test time limit so an engine that loops forever fails instead of hanging."""

import signal
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for candidate in (ROOT / "src", ROOT):
    if candidate.is_dir() and str(candidate) not in sys.path:
        sys.path.insert(0, str(candidate))

TIME_LIMIT_SECONDS = 10


@pytest.fixture(autouse=True)
def time_limit():
    def expired(signum, frame):
        raise TimeoutError(f"test exceeded {TIME_LIMIT_SECONDS}s (catastrophic backtracking or infinite loop?)")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.alarm(TIME_LIMIT_SECONDS)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, previous)
