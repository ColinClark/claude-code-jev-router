import fcntl
import json
import os
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any


class Store:
    def __init__(self, path: str | os.PathLike[str]) -> None:
        self.path = os.fspath(path)
        self._lock_path = self.path + ".lock"

    def get(self, key: str, default: Any = None) -> Any:
        entry = self._load().get(key)
        if entry is None or _expired(entry, time.time()):
            return default
        return entry["value"]

    def set(self, key: str, value: Any, ttl: float | None = None) -> None:
        with self._exclusive():
            now = time.time()
            data = _live(self._load(), now)
            data[key] = {"value": value, "expires_at": None if ttl is None else now + ttl}
            self._write(data)

    def delete(self, key: str) -> None:
        with self._exclusive():
            data = _live(self._load(), time.time())
            data.pop(key, None)
            self._write(data)

    def keys(self) -> list[str]:
        return list(_live(self._load(), time.time()))

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        # The lock lives on a separate file because os.replace swaps the data file's
        # inode: a lock held on the old data file would not exclude a writer that
        # opened the new one, and two writers could then both read the same snapshot.
        with open(self._lock_path, "a") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _load(self) -> dict[str, dict[str, Any]]:
        # Reads need no lock: writers publish via atomic os.replace, so a reader
        # always sees either the complete old file or the complete new one.
        try:
            with open(self.path, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def _write(self, data: dict[str, dict[str, Any]]) -> None:
        text = json.dumps(data)
        directory = os.path.dirname(os.path.abspath(self.path))
        tmp = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=directory,
            prefix=os.path.basename(self.path) + ".",
            suffix=".tmp",
            delete=False,
        )
        try:
            with tmp:
                tmp.write(text)
                tmp.flush()
                os.fsync(tmp.fileno())
            os.replace(tmp.name, self.path)
        except BaseException:
            try:
                os.unlink(tmp.name)
            except FileNotFoundError:
                pass
            raise


def _expired(entry: dict[str, Any], now: float) -> bool:
    expires_at = entry.get("expires_at")
    return expires_at is not None and expires_at <= now


def _live(data: dict[str, dict[str, Any]], now: float) -> dict[str, dict[str, Any]]:
    return {k: v for k, v in data.items() if not _expired(v, now)}
