"""Command-line interface: ``python -m tinykv --db PATH {set,get,del,keys} ...``."""

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


def _format_value(value: object) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv", description="Tiny persistent key-value store")
    parser.add_argument("--db", required=True, help="path to the JSON database file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="set KEY to VALUE (parsed as JSON if valid)")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--ttl", type=float, default=None, help="expire after SECONDS")

    p_get = sub.add_parser("get", help="print the value of KEY (exit 1 if missing)")
    p_get.add_argument("key")

    p_del = sub.add_parser("del", help="delete KEY (exit 1 if missing)")
    p_del.add_argument("key")

    sub.add_parser("keys", help="list live keys, one per line")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        if args.ttl is not None and args.ttl <= 0:
            print("tinykv: --ttl must be positive", file=sys.stderr)
            return 2
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
        return 0
    if args.command == "get":
        value = store.get(args.key, _MISSING)
        if value is _MISSING:
            print(f"tinykv: key not found: {args.key}", file=sys.stderr)
            return 1
        print(_format_value(value))
        return 0
    if args.command == "del":
        return 0 if store.delete(args.key) else 1
    if args.command == "keys":
        for key in store.keys():
            print(key)
        return 0
    raise AssertionError(f"unhandled command {args.command!r}")


if __name__ == "__main__":
    sys.exit(main())
