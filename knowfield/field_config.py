from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .known_fields import get_known_field


def slugify(value: str, default: str = "") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or default


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _keyword_groups(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        return {}
    groups: dict[str, list[str]] = {}
    for name, items in value.items():
        clean_name = str(name).strip()
        if clean_name:
            groups[clean_name] = _string_list(items)
    return groups


@dataclass
class FieldConfig:
    field_name: str
    output_slug: str = ""
    aliases: list[str] = field(default_factory=list)
    description: str = ""
    why_it_matters: str = ""
    seed_keywords: dict[str, list[str]] = field(default_factory=dict)
    starter_questions: list[str] = field(default_factory=list)
    timeline: list[str] = field(default_factory=list)
    hot_topics: list[str] = field(default_factory=list)
    solved_problems: list[str] = field(default_factory=list)
    open_problems: list[str] = field(default_factory=list)
    learning_path: list[str] = field(default_factory=list)
    starter_projects: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        for candidate in [self.output_slug, self.field_name, *self.aliases]:
            slug = slugify(candidate)
            if slug:
                return slug
        return "field"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "FieldConfig":
        field_name = str(data.get("field_name") or data.get("topic") or "").strip()
        if not field_name:
            raise ValueError("field config must include field_name")
        return cls(
            field_name=field_name,
            output_slug=str(data.get("slug") or data.get("output_slug") or "").strip(),
            aliases=_string_list(data.get("aliases")),
            description=str(data.get("description") or "").strip(),
            why_it_matters=str(data.get("why_it_matters") or "").strip(),
            seed_keywords=_keyword_groups(data.get("seed_keywords")),
            starter_questions=_string_list(data.get("starter_questions")),
            timeline=_string_list(data.get("timeline")),
            hot_topics=_string_list(data.get("hot_topics")),
            solved_problems=_string_list(data.get("solved_problems")),
            open_problems=_string_list(data.get("open_problems")),
            learning_path=_string_list(data.get("learning_path")),
            starter_projects=_string_list(data.get("starter_projects")),
            sources=_string_list(data.get("sources")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "field_name": self.field_name,
            "slug": self.slug,
            "aliases": self.aliases,
            "description": self.description,
            "why_it_matters": self.why_it_matters,
            "seed_keywords": self.seed_keywords,
            "starter_questions": self.starter_questions,
            "timeline": self.timeline,
            "hot_topics": self.hot_topics,
            "solved_problems": self.solved_problems,
            "open_problems": self.open_problems,
            "learning_path": self.learning_path,
            "starter_projects": self.starter_projects,
            "sources": self.sources,
        }


def load_field_config(path: Path) -> FieldConfig:
    with path.open(encoding="utf-8") as config_file:
        data = json.load(config_file)
    if not isinstance(data, dict):
        raise ValueError("field config must be a JSON object")
    return FieldConfig.from_dict(data)


def create_template(topic: str) -> FieldConfig:
    clean_topic = topic.strip()
    if not clean_topic:
        raise ValueError("topic cannot be empty")
    known = get_known_field(clean_topic)
    if known:
        return FieldConfig.from_dict(known)
    return FieldConfig(
        field_name=clean_topic,
        aliases=[],
        description="",
        why_it_matters="",
        seed_keywords={
            "plain_language": [
                f"what is {clean_topic}",
                f"{clean_topic} explained",
            ],
            "academic": [
                f"{clean_topic} survey",
                f"{clean_topic} tutorial",
            ],
            "engineering": [
                f"{clean_topic} open source",
                f"{clean_topic} system",
            ],
            "practice": [
                f"{clean_topic} use cases",
                f"{clean_topic} challenges",
            ],
        },
        starter_questions=[
            f"What problem does {clean_topic} solve?",
            f"Why did {clean_topic} appear?",
            f"What is already mature in {clean_topic}?",
            f"What remains difficult in {clean_topic}?",
            f"How can a beginner go deeper into {clean_topic}?",
        ],
    )


def write_field_config(config: FieldConfig, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as config_file:
        json.dump(config.to_dict(), config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")
