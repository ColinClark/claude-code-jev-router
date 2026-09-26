"""Command-line interface for tinykv."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tinykv.store import Store, StoreCorruptError

_MISSING = object()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv")
    parser.add_argument("--db", required=True, help="path to the database file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="set a key to a value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument("--ttl", type=float, default=None, help="expiry in seconds")

    get_parser = subparsers.add_parser("get", help="get the value for a key")
    get_parser.add_argument("key")

    del_parser = subparsers.add_parser("del", help="delete a key")
    del_parser.add_argument("key")

    subparsers.add_parser("keys", help="list all live keys")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    store = Store(args.db)

    try:
        if args.command == "set":
            try:
                value = json.loads(args.value)
            except json.JSONDecodeError:
                value = args.value
            store.set(args.key, value, ttl=args.ttl)
            return 0

        if args.command == "get":
            value = store.get(args.key, default=_MISSING)
            if value is _MISSING:
                print(f"tinykv: key {args.key!r} not found", file=sys.stderr)
                return 1
            if isinstance(value, str):
                print(value)
            else:
                print(json.dumps(value))
            return 0

        if args.command == "del":
            removed = store.delete(args.key)
            if not removed:
                print(f"tinykv: key {args.key!r} not found", file=sys.stderr)
                return 1
            return 0

        if args.command == "keys":
            for key in store.keys():
                print(key)
            return 0

        parser.error(f"unknown command {args.command!r}")
        return 2
    except StoreCorruptError as exc:
        print(f"tinykv: {exc}", file=sys.stderr)
        return 2
    except (TypeError, ValueError) as exc:
        print(f"tinykv: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
