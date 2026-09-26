"""A tiny, stdlib-only key-value store."""

from tinykv.store import Store, StoreCorruptError

__all__ = ["Store", "StoreCorruptError"]
