"""Command-line interface: ``python -m tinykv --db PATH <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tinykv.store import Store

_MISSING = object()


def _parse_value(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv", description="A small persistent KV store.")
    parser.add_argument("--db", required=True, help="path to the JSON database file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="set KEY to VALUE (parsed as JSON if valid)")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--ttl", type=float, default=None, help="time to live in seconds")

    sub.add_parser("get", help="print the value of KEY").add_argument("key")
    sub.add_parser("del", help="delete KEY").add_argument("key")
    sub.add_parser("keys", help="list live keys, one per line")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
        return 0
    if args.command == "get":
        value = store.get(args.key, _MISSING)
        if value is _MISSING:
            print(f"tinykv: key not found: {args.key}", file=sys.stderr)
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
        return 0
    if args.command == "del":
        if store.delete(args.key):
            return 0
        print(f"tinykv: key not found: {args.key}", file=sys.stderr)
        return 1
    for key in store.keys():  # "keys"
        print(key)
    return 0
