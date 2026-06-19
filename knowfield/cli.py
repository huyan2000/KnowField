from __future__ import annotations

import argparse
import json
from pathlib import Path

from .field_config import create_template, load_field_config, write_field_config
from .report import write_report_bundle
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
    init_parser = subparsers.add_parser("init", help="create a field config template")
    init_parser.add_argument("topic", help="field or topic name")
    init_parser.add_argument("-o", "--output", type=Path, help="output JSON path")

    map_parser = subparsers.add_parser("map", help="create a starter field report from a topic or config file")
    map_parser.add_argument("topic_or_config", help="field name or field config JSON path")
    map_parser.add_argument("-o", "--output", type=Path, help="output directory")

    args = parser.parse_args(argv)
    if args.command == "schema":
        print_schema()
        return
    if args.command == "init":
        config = create_template(args.topic)
        output_path = args.output or Path(f"{config.slug}.json")
        write_field_config(config, output_path)
        print(f"Created field config: {output_path}")
        return
    if args.command == "map":
        candidate_path = Path(args.topic_or_config)
        if candidate_path.exists():
            config = load_field_config(candidate_path)
        else:
            config = create_template(args.topic_or_config)
        output_dir = args.output or Path("outputs") / config.slug
        paths = write_report_bundle(config, output_dir)
        print(f"Created field starter report in: {output_dir}")
        for path in paths:
            print(f"- {path}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
