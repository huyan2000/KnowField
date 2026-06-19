# KnowField / 知域

Understand a field before you dive in.

KnowField is an open-source field understanding tool for people who want to quickly understand an unfamiliar domain. Instead of only explaining what a term means, KnowField aims to build a field map: why the field appeared, how it developed, what stage it is in, what people are working on now, what problems remain unsolved, and how a beginner can go deeper.

> 中文定位：知域帮助普通人从“听说过一个词”，走到“知道这个领域大概是怎么回事、发展到哪一步、下一步该怎么深入”。

## Project Status

This repository is in an early alpha stage.

The currently usable product path is:

1. enter a topic;
2. collect public paper links and metadata;
3. generate a beginner reading list with reasons;
4. keep the search basis and raw metadata for verification;
5. prepare a prompt file for paper explanation.

The next layer of KnowField will connect these evidence sources to fuller field maps, maturity signals, hot topics, open problems, and learning paths.

## Quick Start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Start with a topic and collect paper links:

```bash
knowfield collect "边缘计算" --limit 8
```

This writes a paper reading list, the search basis, raw metadata, and a prompt file for paper explanation:

```text
outputs/edge-computing/field_config.json
outputs/edge-computing/collection_basis.md
outputs/edge-computing/papers.json
outputs/edge-computing/papers.csv
outputs/edge-computing/paper_reading_list.md
outputs/edge-computing/paper_explanation_prompt.md
```

Print the planned field report schema:

```bash
knowfield schema
```

Create a starter field report from only a topic name:

```bash
knowfield map "edge computing"
```

English topics also work:

```bash
knowfield collect "edge computing" --limit 8
```

For common Chinese topics such as `边缘计算`, `训练框架`, and `推理框架`, KnowField includes a small starter profile so the first output is less empty.

This writes a first report and an editable config file:

```text
outputs/edge-computing/field_config.json
outputs/edge-computing/field_report.md
outputs/edge-computing/keywords.json
outputs/edge-computing/learning_path.md
outputs/edge-computing/starter_questions.md
```

You can then edit `outputs/edge-computing/field_config.json` and run:

```bash
knowfield map outputs/edge-computing/field_config.json
```

If you only want to create a config template:

```bash
knowfield init "edge computing" -o edge_computing.json
```

You can also create a report from an existing config:

```bash
knowfield map examples/fields/edge_computing.json
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
