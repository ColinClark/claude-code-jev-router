"""Command-line interface: ``python -m tinykv --db PATH <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tinykv.store import Store

_MISSING = object()


def _parse_value(text: str) -> object:
    """Interpret VALUE as JSON when possible, otherwise keep it as a string."""
    try:
        return json.loads(text)
    except ValueError:
        return text


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tinykv", description="A tiny persistent key-value store."
    )
    parser.add_argument("--db", required=True, help="path to the JSON database file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="store a value")
    p_set.add_argument("key")
    p_set.add_argument("value", help="JSON literal if parseable, otherwise a plain string")
    p_set.add_argument("--ttl", type=float, default=None, help="time to live in seconds")

    p_get = sub.add_parser("get", help="print a value; exit 1 if missing or expired")
    p_get.add_argument("key")

    p_del = sub.add_parser("del", help="delete a key")
    p_del.add_argument("key")

    sub.add_parser("keys", help="list live keys, one per line")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        if args.ttl is not None and args.ttl <= 0:
            print("error: --ttl must be positive", file=sys.stderr)
            return 2
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
        return 0

    if args.command == "get":
        value = store.get(args.key, _MISSING)
        if value is _MISSING:
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
        return 0

    if args.command == "del":
        store.delete(args.key)
        return 0

    if args.command == "keys":
        for key in store.keys():
            print(key)
        return 0

    return 2  # pragma: no cover - argparse rejects unknown commands
