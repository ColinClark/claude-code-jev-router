"""Command-line interface: ``python -m tinykv --db PATH <command> ...``."""

from __future__ import annotations

import argparse
import json
import sys

from tinykv.store import Store

_MISSING = object()


def _parse_value(raw: str) -> object:
    """Interpret VALUE as JSON when possible, otherwise as a plain string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m tinykv", description=__doc__)
    parser.add_argument("--db", required=True, help="path to the JSON database file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="set KEY to VALUE (parsed as JSON if valid)")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--ttl", type=float, help="expire after SECONDS")

    p_get = sub.add_parser("get", help="print the value of KEY as JSON")
    p_get.add_argument("key")

    p_del = sub.add_parser("del", help="delete KEY")
    p_del.add_argument("key")

    sub.add_parser("keys", help="list live keys, one per line")

    args = parser.parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        if args.ttl is not None and args.ttl <= 0:
            parser.error("--ttl must be positive")
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
    elif args.command == "get":
        value = store.get(args.key, default=_MISSING)
        if value is _MISSING:
            print(f"key not found: {args.key}", file=sys.stderr)
            return 1
        print(json.dumps(value))
    elif args.command == "del":
        if not store.delete(args.key):
            print(f"key not found: {args.key}", file=sys.stderr)
            return 1
    elif args.command == "keys":
        for key in store.keys():
            print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
