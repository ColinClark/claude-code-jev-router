"""Command-line interface for tinykv."""

from __future__ import annotations

import argparse
import json
import sys

from tinykv.store import Store

_MISSING = object()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv", description="Tiny persistent key-value store")
    parser.add_argument("--db", required=True, help="path to the store file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="set a key to a value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument("--ttl", type=float, default=None, help="time to live in seconds")

    get_parser = subparsers.add_parser("get", help="get the value of a key")
    get_parser.add_argument("key")

    del_parser = subparsers.add_parser("del", help="delete a key")
    del_parser.add_argument("key")

    subparsers.add_parser("keys", help="list all live keys")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    store = Store(args.db)

    if args.command == "set":
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        try:
            store.set(args.key, value, ttl=args.ttl)
        except (ValueError, TypeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "get":
        result = store.get(args.key, default=_MISSING)
        if result is _MISSING:
            print(f"error: key {args.key!r} not found", file=sys.stderr)
            return 1
        print(json.dumps(result))
        return 0

    if args.command == "del":
        deleted = store.delete(args.key)
        if not deleted:
            print(f"error: key {args.key!r} not found", file=sys.stderr)
            return 1
        return 0

    if args.command == "keys":
        for key in store.keys():
            print(key)
        return 0

    parser.error(f"unknown command {args.command!r}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
