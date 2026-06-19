from __future__ import annotations

import argparse
import json
from pathlib import Path

from .collector import collect_papers, write_collection_bundle
from .field_config import create_template, load_field_config, write_field_config
from .report import write_report_bundle
from .schema import FIELD_REPORT_SCHEMA, MATURITY_LEVELS


def print_schema() -> None:
    print(json.dumps({
        "field_report_schema": FIELD_REPORT_SCHEMA,
        "maturity_levels": MATURITY_LEVELS,
    }, ensure_ascii=False, indent=2))


def load_topic_or_config(value: str):
    candidate_path = Path(value)
    if candidate_path.exists():
        return load_field_config(candidate_path)
    return create_template(value)


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

    collect_parser = subparsers.add_parser("collect", help="collect paper links and reading reasons")
    collect_parser.add_argument("topic_or_config", help="field name or field config JSON path")
    collect_parser.add_argument("-o", "--output", type=Path, help="output directory")
    collect_parser.add_argument("--limit", type=int, default=12, help="maximum papers to keep")
    collect_parser.add_argument("--max-per-keyword", type=int, default=5, help="maximum papers per keyword")
    collect_parser.add_argument("--pause", type=float, default=1.0, help="pause between source requests")

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
        config = load_topic_or_config(args.topic_or_config)
        output_dir = args.output or Path("outputs") / config.slug
        paths = write_report_bundle(config, output_dir)
        print(f"Created field starter report in: {output_dir}")
        for path in paths:
            print(f"- {path}")
        return
    if args.command == "collect":
        config = load_topic_or_config(args.topic_or_config)
        output_dir = args.output or Path("outputs") / config.slug
        papers = collect_papers(
            config,
            max_per_keyword=args.max_per_keyword,
            limit=args.limit,
            pause=args.pause,
        )
        paths = write_collection_bundle(config, papers, output_dir)
        print(f"Collected {len(papers)} paper candidates in: {output_dir}")
        for path in paths:
            print(f"- {path}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
