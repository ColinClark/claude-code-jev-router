"""Command-line interface: python -m tinykv --db PATH {set,get,del,keys}."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from tinykv.store import Store


def _parse_value(raw: str) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv", description="Tiny key-value store")
    parser.add_argument("--db", required=True, help="path to the database file")
    sub = parser.add_subparsers(dest="command", required=True)
    p_set = sub.add_parser("set", help="set a key")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--ttl", type=float, default=None, help="expiry in seconds")
    p_get = sub.add_parser("get", help="get a key")
    p_get.add_argument("key")
    p_del = sub.add_parser("del", help="delete a key")
    p_del.add_argument("key")
    sub.add_parser("keys", help="list keys")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    store = Store(args.db)
    if args.command == "set":
        try:
            store.set(args.key, _parse_value(args.value), ttl=args.ttl)
        except (TypeError, ValueError) as exc:
            print(f"tinykv: error: {exc}", file=sys.stderr)
            return 2
        return 0
    if args.command == "get":
        missing = object()
        value = store.get(args.key, missing)
        if value is missing:
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
        return 0
    if args.command == "del":
        return 0 if store.delete(args.key) else 1
    for key in store.keys():
        print(key)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
