from __future__ import annotations

import csv
import json
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

import requests

from .field_config import FieldConfig

ARXIV_API = "https://export.arxiv.org/api/query"
USER_AGENT = "knowfield/0.1"
SOURCE_NAME = "arXiv"


@dataclass
class PaperItem:
    id: str
    title: str
    authors: list[str]
    year: int
    summary: str
    page_url: str
    pdf_url: str
    categories: list[str]
    matched_keywords: list[str]
    score: int
    reasons: list[str]


def _clean_text(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _arxiv_id_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def _phrase_query(keyword: str) -> str:
    clean_keyword = keyword.strip()
    if not clean_keyword:
        return ""
    if re.search(r"\s", clean_keyword):
        return f'all:"{clean_keyword}"'
    return f"all:{clean_keyword}"


def _is_probably_paper_query(keyword: str) -> bool:
    if re.search(r"[\u4e00-\u9fff]", keyword):
        return False
    lowered = keyword.lower()
    weak_terms = ("what is ", "explained", "入门")
    return not any(term in lowered for term in weak_terms)


def build_search_keywords(config: FieldConfig, limit: int = 8) -> list[str]:
    keywords: list[str] = []
    for alias in config.aliases:
        keywords.append(alias)
    for group in ("academic", "engineering", "practice", "industry", "plain_language"):
        keywords.extend(config.seed_keywords.get(group, []))

    deduped: list[str] = []
    seen: set[str] = set()
    for keyword in keywords:
        clean_keyword = keyword.strip()
        if not clean_keyword or not _is_probably_paper_query(clean_keyword):
            continue
        key = clean_keyword.lower()
        if key not in seen:
            seen.add(key)
            deduped.append(clean_keyword)
    return deduped[:limit]


def fetch_arxiv_for_keyword(keyword: str, max_results: int) -> list[PaperItem]:
    query = _phrase_query(keyword)
    if not query:
        return []
    params = {
        "search_query": query,
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    papers: list[PaperItem] = []
    for entry in root.findall("atom:entry", ns):
        page_url = _clean_text(entry.findtext("atom:id", namespaces=ns))
        paper_id = _arxiv_id_from_url(page_url)
        title = _clean_text(entry.findtext("atom:title", namespaces=ns))
        summary = _clean_text(entry.findtext("atom:summary", namespaces=ns))
        published = _clean_text(entry.findtext("atom:published", namespaces=ns))
        try:
            year = datetime.fromisoformat(published.replace("Z", "+00:00")).year
        except ValueError:
            year = 0
        authors = [
            _clean_text(author.findtext("atom:name", namespaces=ns))
            for author in entry.findall("atom:author", ns)
        ]
        categories = [
            category.attrib.get("term", "")
            for category in entry.findall("atom:category", ns)
            if category.attrib.get("term")
        ]
        pdf_url = ""
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "")
                break
        papers.append(PaperItem(
            id=paper_id,
            title=title,
            authors=authors,
            year=year,
            summary=summary,
            page_url=page_url,
            pdf_url=pdf_url or f"https://arxiv.org/pdf/{paper_id}",
            categories=categories,
            matched_keywords=[keyword],
            score=0,
            reasons=[],
        ))
    return papers


def _score_paper(paper: PaperItem, config: FieldConfig) -> None:
    text = f"{paper.title} {paper.summary}".lower()
    reasons: list[str] = []
    score = 0

    for keyword in build_search_keywords(config, limit=20):
        if keyword.lower() in text:
            paper.matched_keywords.append(keyword)

    unique_matches = sorted(set(paper.matched_keywords), key=str.lower)
    paper.matched_keywords = unique_matches
    score += min(len(unique_matches) * 2, 8)
    if unique_matches:
        reasons.append(f"匹配关键词：{', '.join(unique_matches[:3])}")

    title_lower = paper.title.lower()
    if "survey" in title_lower or "review" in title_lower:
        score += 8
        reasons.append("标题像综述，适合快速建立全局认识")
    if "tutorial" in title_lower or "benchmark" in title_lower:
        score += 5
        reasons.append("可能包含教程、评测或系统化比较")
    if paper.year >= datetime.now(timezone.utc).year - 2:
        score += 3
        reasons.append("年份较新，适合观察近期方向")
    if any(term in text for term in ["challenge", "open problem", "limitation", "future work"]):
        score += 4
        reasons.append("可能讨论挑战或未解决问题")
    if any(term in text for term in ["system", "framework", "architecture", "deployment"]):
        score += 3
        reasons.append("可能包含系统、框架或落地视角")

    paper.score = score
    paper.reasons = reasons or ["与当前领域关键词相关，可作为候选阅读材料"]


def collect_papers(config: FieldConfig, *, max_per_keyword: int = 5, limit: int = 12, pause: float = 1.0) -> list[PaperItem]:
    by_id: dict[str, PaperItem] = {}
    for keyword in build_search_keywords(config):
        try:
            fetched_papers = fetch_arxiv_for_keyword(keyword, max_per_keyword)
        except requests.RequestException:
            continue
        for paper in fetched_papers:
            if paper.id in by_id:
                by_id[paper.id].matched_keywords.extend(paper.matched_keywords)
            else:
                by_id[paper.id] = paper
        if pause > 0:
            time.sleep(pause)

    papers = list(by_id.values())
    for paper in papers:
        _score_paper(paper, config)
    papers.sort(key=lambda item: (item.score, item.year), reverse=True)
    return papers[:limit]


def _write_json(papers: list[PaperItem], path: Path) -> None:
    with path.open("w", encoding="utf-8") as json_file:
        json.dump([asdict(paper) for paper in papers], json_file, ensure_ascii=False, indent=2)
        json_file.write("\n")


def _write_csv(papers: list[PaperItem], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as csv_file:
        writer = csv.writer(csv_file)
        writer.writerow(["title", "year", "score", "reasons", "page_url", "pdf_url", "matched_keywords"])
        for paper in papers:
            writer.writerow([
                paper.title,
                paper.year,
                paper.score,
                "；".join(paper.reasons),
                paper.page_url,
                paper.pdf_url,
                "；".join(paper.matched_keywords),
            ])


def _write_markdown(config: FieldConfig, papers: list[PaperItem], path: Path) -> None:
    lines = [
        f"# {config.field_name} 推荐阅读清单",
        "",
        "这份清单来自公开论文元数据搜索。它的作用是先给学习者一批可点击的论文入口，并说明为什么这些论文值得先看。",
        "",
        "## 推荐顺序",
        "",
    ]
    if not papers:
        lines.extend([
            "暂时没有找到候选论文。可以尝试补充英文别名或更具体的关键词后重新运行。",
            "",
        ])
    for index, paper in enumerate(papers, start=1):
        authors = ", ".join(paper.authors[:4])
        if len(paper.authors) > 4:
            authors += ", et al."
        lines.extend([
            f"### {index}. {paper.title}",
            "",
            f"- 年份：{paper.year or 'unknown'}",
            f"- 作者：{authors or 'unknown'}",
            f"- 链接：{paper.page_url}",
            f"- PDF：{paper.pdf_url}",
            f"- 匹配关键词：{', '.join(paper.matched_keywords) or 'none'}",
            f"- 为什么先看：{'；'.join(paper.reasons)}",
            f"- 摘要预览：{paper.summary[:500]}{'...' if len(paper.summary) > 500 else ''}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_model_prompt(config: FieldConfig, papers: list[PaperItem], path: Path) -> None:
    selected = papers[:5]
    lines = [
        f"# {config.field_name} 论文解释提示词",
        "",
        "把下面论文解释给一个刚入门的读者。每篇论文请回答：",
        "",
        "1. 这篇论文想解决什么问题？",
        "2. 它为什么值得看？",
        "3. 它和这个领域的哪些方向有关？",
        "4. 它可能难在哪里？",
        "5. 初学者应该先看标题、摘要、图、实验还是结论？",
        "",
        "论文列表：",
        "",
    ]
    for paper in selected:
        lines.extend([
            f"- 标题：{paper.title}",
            f"  年份：{paper.year}",
            f"  链接：{paper.page_url}",
            f"  摘要：{paper.summary}",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_basis(config: FieldConfig, papers: list[PaperItem], path: Path) -> None:
    keywords = build_search_keywords(config)
    lines = [
        f"# {config.field_name} 生成依据",
        "",
        "这份结果不是凭空生成的，而是先用领域关键词搜索公开论文元数据，再按可解释规则排序。",
        "",
        "## 数据来源",
        "",
        f"- {SOURCE_NAME} 公开论文元数据接口",
        "- 当前版本只保存论文标题、作者、年份、摘要、链接和匹配关键词，不下载 PDF。",
        "",
        "## 搜索词",
        "",
    ]
    if keywords:
        lines.extend(f"- {keyword}" for keyword in keywords)
    else:
        lines.append("- 暂时没有可用于论文检索的英文关键词。")
    lines.extend([
        "",
        "## 排序依据",
        "",
        "- 关键词匹配越多，优先级越高。",
        "- 标题包含 survey 或 review 的论文更适合作为入门全景材料。",
        "- 标题包含 tutorial 或 benchmark 的论文更适合建立比较视角。",
        "- 最近两年的论文更适合观察近期方向。",
        "- 摘要提到 challenge、open problem、limitation 或 future work 时，更适合观察未解决问题。",
        "- 摘要提到 system、framework、architecture 或 deployment 时，更适合观察工程落地。",
        "",
        "## 判断边界",
        "",
        "- 这份清单只能说明这些论文和当前关键词高度相关，不代表完整覆盖整个领域。",
        "- 初学者应优先读综述、评测和系统论文，再根据反复出现的关键词继续追踪。",
        f"- 本次共保留 {len(papers)} 篇候选论文。",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def write_collection_bundle(config: FieldConfig, papers: list[PaperItem], output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    config_path = output_dir / "field_config.json"
    basis_path = output_dir / "collection_basis.md"
    json_path = output_dir / "papers.json"
    csv_path = output_dir / "papers.csv"
    reading_path = output_dir / "paper_reading_list.md"
    prompt_path = output_dir / "paper_explanation_prompt.md"

    with config_path.open("w", encoding="utf-8") as config_file:
        json.dump(config.to_dict(), config_file, ensure_ascii=False, indent=2)
        config_file.write("\n")
    _write_basis(config, papers, basis_path)
    _write_json(papers, json_path)
    _write_csv(papers, csv_path)
    _write_markdown(config, papers, reading_path)
    _write_model_prompt(config, papers, prompt_path)
    return [config_path, basis_path, json_path, csv_path, reading_path, prompt_path]
