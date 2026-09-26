"""Command-line entry point for tinykv.

Usage::

    python -m tinykv --db PATH set KEY VALUE [--ttl SECONDS]
    python -m tinykv --db PATH get KEY
    python -m tinykv --db PATH del KEY
    python -m tinykv --db PATH keys
"""

import argparse
import json
import sys

from tinykv.store import Store


def _parse_value(raw: str) -> object:
    """Parse ``raw`` as JSON if possible, else return it unchanged as a string."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


def _build_parser() -> argparse.ArgumentParser:
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

    subparsers.add_parser("keys", help="List all keys")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    store = Store(args.db)

    if args.command == "set":
        value = _parse_value(args.value)
        store.set(args.key, value, ttl=args.ttl)
    elif args.command == "get":
        try:
            value = store.get(args.key)
        except KeyError:
            print(f"key not found: {args.key}", file=sys.stderr)
            sys.exit(1)
        if isinstance(value, str):
            print(value)
        else:
            print(json.dumps(value))
    elif args.command == "del":
        # Treat `del` as idempotent from the CLI's perspective: deleting an
        # already-missing or expired key is not an error.
        try:
            store.delete(args.key)
        except KeyError:
            pass
    elif args.command == "keys":
        all_keys = store.keys()
        for key in all_keys:
            print(key)


if __name__ == "__main__":
    main()
