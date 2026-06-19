# KnowField / 知域

Understand a field before you dive in.

KnowField is an open-source field understanding tool for people who want to quickly understand an unfamiliar domain. Instead of only explaining what a term means, KnowField aims to build a field map: why the field appeared, how it developed, what stage it is in, what people are working on now, what problems remain unsolved, and how a beginner can go deeper.

> 中文定位：知域帮助普通人从“听说过一个词”，走到“知道这个领域大概是怎么回事、发展到哪一步、下一步该怎么深入”。

## Project Status

This repository is in an early alpha stage.

The currently usable part is the paper discovery and report-generation engine under `paper_search/`. It can:

- search paper metadata from academic metadata services;
- track recent arXiv papers;
- reconcile local PDFs with paper metadata;
- generate local CSV/HTML reports.

The next layer of KnowField will turn those evidence sources into plain-language field maps, maturity signals, hot topics, open problems, and learning paths.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Run the current paper discovery workflow:

```bash
cd paper_search
export S2_API_KEY="your_metadata_api_key"  # optional
python3 paper_search_crawler.py
```

Regenerate reports from existing local files:

```bash
cd paper_search
python3 paper_search_crawler.py --reports-only --skip-arxiv
```

Print the planned field report schema:

```bash
knowfield schema
```

Create a new field config:

```bash
knowfield init "edge computing" -o edge_computing.json
```

Create a starter field report from a config:

```bash
knowfield map examples/fields/edge_computing.json
```

The command writes:

```text
outputs/edge-computing/field_report.md
outputs/edge-computing/keywords.json
outputs/edge-computing/learning_path.md
outputs/edge-computing/starter_questions.md
```

## What KnowField Tries to Answer

For a topic such as `edge computing`, KnowField should eventually produce:

- plain-language explanation;
- why the field appeared;
- development timeline;
- current maturity stage;
- current hot topics;
- solved and unsolved problems;
- key papers, projects, organizations, and standards;
- learning path for beginners;
- starter projects for hands-on learning.

## Repository Layout

```text
knowfield/              # product-facing CLI and field schema
paper_search/           # current usable paper discovery engine
docs/                   # design notes and public documentation
examples/fields/        # example field seed configurations
```

## Privacy and Copyright Notes

This repository intentionally does not include:

- downloaded PDFs;
- private reading notes;
- local reports containing absolute paths;
- API keys or local environment files;
- IDE workspace files.

Please respect publishers' terms of service and copyright restrictions when downloading or storing papers.

## License

MIT License.
