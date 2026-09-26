"""Command-line interface for tinykv: ``python -m tinykv``."""

from __future__ import annotations

import argparse
import json
import sys

from tinykv.store import Store

_MISSING = object()


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv", description="Tiny JSON key-value store")
    parser.add_argument("--db", required=True, help="path to the JSON store file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="set a key")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--ttl", type=float, default=None, help="time to live in seconds")

    p_get = sub.add_parser("get", help="get a key")
    p_get.add_argument("key")

    p_del = sub.add_parser("del", help="delete a key")
    p_del.add_argument("key")

    sub.add_parser("keys", help="list keys")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
        return 0
    if args.command == "get":
        value = store.get(args.key, _MISSING)
        if value is _MISSING:
            print(f"key not found: {args.key}", file=sys.stderr)
            return 1
        print(json.dumps(value))
        return 0
    if args.command == "del":
        store.delete(args.key)
        return 0
    if args.command == "keys":
        for key in store.keys():
            print(key)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
