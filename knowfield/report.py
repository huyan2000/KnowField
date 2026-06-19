from __future__ import annotations

import json
from pathlib import Path

from .field_config import FieldConfig


def _bullet_list(items: list[str], empty_message: str) -> str:
    if not items:
        return f"- {empty_message}\n"
    return "".join(f"- {item}\n" for item in items)


def _numbered_list(items: list[str], empty_message: str) -> str:
    if not items:
        return f"1. {empty_message}\n"
    return "".join(f"{index}. {item}\n" for index, item in enumerate(items, start=1))


def _keyword_section(config: FieldConfig) -> str:
    if not config.seed_keywords:
        return "- Add seed keywords to the field config.\n"

    sections: list[str] = []
    for group, keywords in config.seed_keywords.items():
        sections.append(f"### {group}\n")
        sections.append(_bullet_list(keywords, "No keywords yet."))
        sections.append("\n")
    return "".join(sections).rstrip() + "\n"


def render_field_report(config: FieldConfig) -> str:
    aliases = ", ".join(config.aliases) if config.aliases else "No aliases yet."
    description = config.description or "Add a plain-language explanation in the field config."
    why_it_matters = config.why_it_matters or "Add why this field matters in the field config."

    return f"""# {config.field_name} 入门地图

这是一份初步入门报告。它的目标不是一次性给出最终答案，而是帮助读者快速看到一个领域的基本含义、关键词、问题、方向和下一步行动。

## 1. 一句话理解

{description}

## 2. 为什么值得了解

{why_it_matters}

## 3. 常见名称

{aliases}

## 4. 关键词入口

{_keyword_section(config)}

## 5. 入门时先问的问题

{_numbered_list(config.starter_questions, "Add starter questions to the field config.")}

## 6. 发展线索

{_bullet_list(config.timeline, "Add timeline notes after reading introductory sources.")}

## 7. 当前常见方向

{_bullet_list(config.hot_topics, "Add current directions after collecting sources.")}

## 8. 已经相对清楚的部分

{_bullet_list(config.solved_problems, "Add mature or well-understood parts after checking sources.")}

## 9. 仍然困难的问题

{_bullet_list(config.open_problems, "Add open problems after checking surveys, docs, and discussions.")}

## 10. 学习路线

{_numbered_list(config.learning_path, "Add a beginner-friendly learning path.")}

## 11. 动手项目

{_numbered_list(config.starter_projects, "Add small starter projects.")}

## 12. 来源记录

{_bullet_list(config.sources, "Add sources used to check this report.")}
"""


def render_learning_path(config: FieldConfig) -> str:
    return f"""# {config.field_name} 学习路线

## 推荐路线

{_numbered_list(config.learning_path, "Add learning steps to the field config.")}

## 建议动手项目

{_numbered_list(config.starter_projects, "Add starter projects to the field config.")}

## 学习时要回答的问题

{_numbered_list(config.starter_questions, "Add starter questions to the field config.")}
"""


def write_report_bundle(config: FieldConfig, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    report_path = output_dir / "field_report.md"
    keywords_path = output_dir / "keywords.json"
    learning_path = output_dir / "learning_path.md"
    questions_path = output_dir / "starter_questions.md"

    report_path.write_text(render_field_report(config), encoding="utf-8")
    learning_path.write_text(render_learning_path(config), encoding="utf-8")
    questions_path.write_text(
        f"# {config.field_name} 入门问题\n\n"
        + _numbered_list(config.starter_questions, "Add starter questions to the field config."),
        encoding="utf-8",
    )
    with keywords_path.open("w", encoding="utf-8") as keywords_file:
        json.dump({
            "field_name": config.field_name,
            "aliases": config.aliases,
            "seed_keywords": config.seed_keywords,
        }, keywords_file, ensure_ascii=False, indent=2)
        keywords_file.write("\n")

    return [report_path, keywords_path, learning_path, questions_path]
