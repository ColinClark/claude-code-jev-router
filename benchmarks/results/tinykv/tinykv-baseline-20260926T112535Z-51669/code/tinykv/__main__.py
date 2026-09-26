"""Command-line interface for tinykv: `python -m tinykv --db PATH <command> ...`."""

from __future__ import annotations

import argparse
import json
import sys

from tinykv.store import Store


def _parse_value(raw: str):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv")
    parser.add_argument("--db", required=True, help="Path to the JSON database file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="Set a key to a value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument("--ttl", type=float, default=None, help="Time-to-live in seconds")

    get_parser = subparsers.add_parser("get", help="Get the value for a key")
    get_parser.add_argument("key")

    del_parser = subparsers.add_parser("del", help="Delete a key")
    del_parser.add_argument("key")

    subparsers.add_parser("keys", help="List all live keys")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
        return 0

    if args.command == "get":
        try:
            value = store.get(args.key)
        except KeyError:
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

    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
