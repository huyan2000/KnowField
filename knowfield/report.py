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
        return "- 还没有关键词。可以先补充几个你会用来搜索这个领域的词。\n"

    sections: list[str] = []
    for group, keywords in config.seed_keywords.items():
        sections.append(f"### {group}\n")
        sections.append(_bullet_list(keywords, "No keywords yet."))
        sections.append("\n")
    return "".join(sections).rstrip() + "\n"


def render_field_report(config: FieldConfig) -> str:
    aliases = ", ".join(config.aliases) if config.aliases else "还没有补充别名。"
    description = config.description or f"这是一份关于 {config.field_name} 的入门地图。当前版本先帮你整理关键词和入门问题，方便继续查资料。"
    why_it_matters = config.why_it_matters or "这一节还没有补充。你可以在后续学习时写下：这个领域解决什么问题、为什么值得关注。"

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

{_numbered_list(config.starter_questions, "先写下你最想弄懂的一个问题。")}

## 6. 发展线索

{_bullet_list(config.timeline, "还没有发展线索。可以先读一篇入门文章或综述，再补充这个领域是怎么发展来的。")}

## 7. 当前常见方向

{_bullet_list(config.hot_topics, "还没有当前方向。可以先从关键词搜索结果中记录反复出现的主题。")}

## 8. 已经相对清楚的部分

{_bullet_list(config.solved_problems, "还没有记录。学习后可以补充哪些概念、方法或应用已经比较清楚。")}

## 9. 仍然困难的问题

{_bullet_list(config.open_problems, "还没有记录。学习后可以补充哪些问题仍然困难、争议较多或没有稳定答案。")}

## 10. 学习路线

{_numbered_list(config.learning_path, "先从关键词入口和入门问题开始，读完资料后再整理学习路线。")}

## 11. 动手项目

{_numbered_list(config.starter_projects, "可以先设计一个很小的观察或动手任务，帮助自己理解这个领域。")}

## 12. 来源记录

{_bullet_list(config.sources, "还没有来源记录。建议把你读过的入门文章、综述、教程或项目链接写在这里。")}
"""


def render_learning_path(config: FieldConfig) -> str:
    return f"""# {config.field_name} 学习路线

## 推荐路线

{_numbered_list(config.learning_path, "先从关键词入口和入门问题开始，读完资料后再整理学习路线。")}

## 建议动手项目

{_numbered_list(config.starter_projects, "可以先设计一个很小的观察或动手任务，帮助自己理解这个领域。")}

## 学习时要回答的问题

{_numbered_list(config.starter_questions, "先写下你最想弄懂的一个问题。")}
"""


def write_report_bundle(config: FieldConfig, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)

    config_path = output_dir / "field_config.json"
    report_path = output_dir / "field_report.md"
    keywords_path = output_dir / "keywords.json"
    learning_path = output_dir / "learning_path.md"
    questions_path = output_dir / "starter_questions.md"

    with config_path.open("w", encoding="utf-8") as config_file:
        json.dump(config.to_dict(), config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")
    report_path.write_text(render_field_report(config), encoding="utf-8")
    learning_path.write_text(render_learning_path(config), encoding="utf-8")
    questions_path.write_text(
        f"# {config.field_name} 入门问题\n\n"
        + _numbered_list(config.starter_questions, "先写下你最想弄懂的一个问题。"),
        encoding="utf-8",
    )
    with keywords_path.open("w", encoding="utf-8") as keywords_file:
        json.dump({
            "field_name": config.field_name,
            "aliases": config.aliases,
            "seed_keywords": config.seed_keywords,
        }, keywords_file, ensure_ascii=False, indent=2)
        keywords_file.write("\n")

    return [config_path, report_path, keywords_path, learning_path, questions_path]
