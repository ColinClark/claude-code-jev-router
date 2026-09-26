import argparse
import json
import sys

from tinykv.store import Store


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tinykv")
    parser.add_argument("--db", required=True, help="Path to the JSON store file")

    subparsers = parser.add_subparsers(dest="command", required=True)

    set_parser = subparsers.add_parser("set", help="Set a key to a value")
    set_parser.add_argument("key")
    set_parser.add_argument("value")
    set_parser.add_argument("--ttl", type=float, default=None, help="Expiry in seconds from now")

    get_parser = subparsers.add_parser("get", help="Get the value for a key")
    get_parser.add_argument("key")

    del_parser = subparsers.add_parser("del", help="Delete a key")
    del_parser.add_argument("key")

    subparsers.add_parser("keys", help="List all non-expired keys")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    store = Store(args.db)

    if args.command == "set":
        try:
            value = json.loads(args.value)
        except json.JSONDecodeError:
            value = args.value
        store.set(args.key, value, ttl=args.ttl)
        sys.exit(0)
    elif args.command == "get":
        value = store.get(args.key)
        if value is None:
            sys.exit(1)
        print(json.dumps(value))
        sys.exit(0)
    elif args.command == "del":
        store.delete(args.key)
        sys.exit(0)
    elif args.command == "keys":
        all_keys = store.keys()
        for key in all_keys:
            print(key)
        sys.exit(0)


if __name__ == "__main__":
    main()
