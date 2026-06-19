from __future__ import annotations

import argparse
import json

from .schema import FIELD_REPORT_SCHEMA, MATURITY_LEVELS


def print_schema() -> None:
    print(json.dumps({
        "field_report_schema": FIELD_REPORT_SCHEMA,
        "maturity_levels": MATURITY_LEVELS,
    }, ensure_ascii=False, indent=2))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="knowfield",
        description="Build plain-language field maps for unfamiliar domains.",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("schema", help="print the planned KnowField report schema")

    args = parser.parse_args(argv)
    if args.command == "schema":
        print_schema()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
