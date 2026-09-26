"""Command-line interface for tinykv.

Usage::

    python -m tinykv --db PATH set KEY VALUE [--ttl SECONDS]
    python -m tinykv --db PATH get KEY
    python -m tinykv --db PATH del KEY
    python -m tinykv --db PATH keys

VALUE is parsed as JSON when possible (so ``42``, ``true`` and ``{"a": 1}`` become numbers,
booleans and objects); anything that is not valid JSON is stored as a plain string.
``get`` prints strings verbatim and every other value as JSON. It exits with status 1 when
the key is missing or expired.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from tinykv.store import Store


def _parse_value(text: str) -> object:
    try:
        return json.loads(text)
    except ValueError:
        return text


def _positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid ttl: {text!r}") from exc
    if value <= 0:
        raise argparse.ArgumentTypeError("ttl must be positive")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tinykv", description="A tiny persistent key-value store."
    )
    parser.add_argument("--db", required=True, metavar="PATH", help="path to the JSON data file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set", help="store a value")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument(
        "--ttl", type=_positive_float, metavar="SECONDS", help="expire after SECONDS"
    )

    p_get = sub.add_parser("get", help="print a value; exit 1 if missing or expired")
    p_get.add_argument("key")

    p_del = sub.add_parser("del", help="delete a key")
    p_del.add_argument("key")

    sub.add_parser("keys", help="list live keys, one per line")
    return parser


_MISSING = object()


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
        store.delete(args.key)
        return 0

    if args.command == "keys":
        for key in store.keys():
            print(key)
        return 0

    raise AssertionError(f"unhandled command {args.command!r}")  # pragma: no cover
