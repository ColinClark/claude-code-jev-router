"""JSON-file backed key-value store with TTL and multi-process safety."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

_MISSING = object()


class Store:
    """Persistent key-value store.

    Data lives in a JSON file ``{key: {"value": ..., "expires": float | None}}``.
    Every operation re-reads the file under an ``fcntl.flock`` on a sidecar
    ``<path>.lock`` file (shared for reads, exclusive for writes); writes are
    atomic via temp file + fsync + ``os.replace``.
    """

    def __init__(self, path: str | os.PathLike[str], clock: Callable[[], float] = time.time):
        self.path = os.fspath(path)
        self.lock_path = self.path + ".lock"
        self.clock = clock

    # -- locking / IO -------------------------------------------------------

    @contextmanager
    def _locked(self, mode: int) -> Iterator[None]:
        fd = os.open(self.lock_path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, mode)
            yield
        finally:
            os.close(fd)  # closing the fd releases the lock

    def _read(self) -> dict[str, dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tinykv-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
            raise

    def _live(self, data: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        now = self.clock()
        return {
            k: e for k, e in data.items() if e.get("expires") is None or e["expires"] > now
        }

    def _expires(self, ttl: float | None) -> float | None:
        return None if ttl is None else self.clock() + ttl

    # -- public API ---------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        with self._locked(fcntl.LOCK_SH):
            entry = self._live(self._read()).get(key)
        return default if entry is None else entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        json.dumps(value)  # fail early on non-serializable values
        with self._locked(fcntl.LOCK_EX):
            data = self._live(self._read())
            data[key] = {"value": value, "expires": self._expires(ttl)}
            self._write(data)

    def delete(self, key: str) -> bool:
        with self._locked(fcntl.LOCK_EX):
            raw = self._read()
            data = self._live(raw)
            existed = data.pop(key, _MISSING) is not _MISSING
            if existed or len(data) != len(raw):
                self._write(data)
        return existed

    def update(self, key: str, fn: Callable[[Any], Any], default: Any = None) -> Any:
        """Atomically replace ``key``'s value with ``fn(current)``; returns the new value.

        The existing TTL of the key is preserved.
        """
        with self._locked(fcntl.LOCK_EX):
            data = self._live(self._read())
            entry = data.get(key)
            new = fn(default if entry is None else entry["value"])
            json.dumps(new)
            data[key] = {"value": new, "expires": entry["expires"] if entry else None}
            self._write(data)
        return new

    def keys(self) -> list[str]:
        with self._locked(fcntl.LOCK_SH):
            return sorted(self._live(self._read()))
