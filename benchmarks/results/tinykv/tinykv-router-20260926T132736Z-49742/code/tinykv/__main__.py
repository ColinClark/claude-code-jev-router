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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="tinykv")
    parser.add_argument("--db", required=True, help="path to the JSON database file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set")
    p_set.add_argument("key")
    p_set.add_argument("value")
    p_set.add_argument("--ttl", type=float, default=None)

    p_get = sub.add_parser("get")
    p_get.add_argument("key")

    p_del = sub.add_parser("del")
    p_del.add_argument("key")

    sub.add_parser("keys")

    args = parser.parse_args(argv)
    store = Store(args.db)

    if args.command == "set":
        store.set(args.key, _parse_value(args.value), ttl=args.ttl)
    elif args.command == "get":
        value = store.get(args.key, _MISSING)
        if value is _MISSING:
            print(f"key not found: {args.key}", file=sys.stderr)
            return 1
        print(json.dumps(value))
    elif args.command == "del":
        store.delete(args.key)
    elif args.command == "keys":
        for key in store.keys():
            print(key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
