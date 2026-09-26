"""Command-line interface: ``python -m tinykv --db PATH {set,get,del,keys} ...``.

VALUE is parsed as JSON when possible (``42``, ``true``, ``{"a": 1}``) and stored as a
plain string otherwise. ``get`` prints strings raw and other values as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys

from tinykv.store import Store

_MISSING = object()


def _parse_value(raw: str) -> object:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv", description="Tiny persistent key-value store.")
    parser.add_argument("--db", required=True, help="path to the JSON database file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="set KEY to VALUE")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--ttl", type=float, default=None, help="expire after SECONDS")

    p_get = sub.add_parser("get", help="print the value of KEY (exit 1 if missing/expired)")
    p_get.add_argument("key")

    p_del = sub.add_parser("del", help="delete KEY")
    p_del.add_argument("key")

    sub.add_parser("keys", help="list live keys, one per line")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        if args.ttl is not None and args.ttl <= 0:
            parser.error("--ttl must be positive")
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
    elif args.command == "get":
        value = store.get(args.key, _MISSING)
        if value is _MISSING:
            print(f"tinykv: key not found: {args.key}", file=sys.stderr)
            return 1
        print(value if isinstance(value, str) else json.dumps(value))
    elif args.command == "del":
        store.delete(args.key)
    elif args.command == "keys":
        for key in store.keys():
            print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
