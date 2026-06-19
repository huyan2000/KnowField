#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fetch highly relevant recent arXiv papers and build a local HTML dashboard.

This script intentionally writes no CSV. It downloads PDFs into
``../PHD-Buyya/arxiv_latest_papers/`` and creates arXiv intermediate reports.
"""

from __future__ import annotations

import html
import csv
import os
import random
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

try:
    import requests
except ImportError as exc:  # pragma: no cover
    raise SystemExit("需要 requests：请先安装 requests") from exc

from utils.paths import find_pdf_root

BASE_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = BASE_DIR.parent
HTML_PATH = BASE_DIR / "arxiv_latest_half_year.html"
CSV_PATH = BASE_DIR / "arxiv_latest_half_year.csv"
DEFAULT_PDF_DIR = find_pdf_root(REPO_DIR, create=True) / "arxiv_latest_papers"


def resolve_pdf_dir() -> Path:
    raw = os.getenv("ARXIV_PDF_DIR")
    if not raw:
        return DEFAULT_PDF_DIR
    path = Path(raw).expanduser()
    return path if path.is_absolute() else (BASE_DIR / path).resolve()


PDF_DIR = resolve_pdf_dir()
ARXIV_API = "https://export.arxiv.org/api/query"
USER_AGENT = "phd-paper-radar/0.3 (local literature review)"
SINCE_DAYS = int(os.getenv("ARXIV_SINCE_DAYS", "183"))
MAX_RESULTS_PER_QUERY = int(os.getenv("ARXIV_MAX_PER_QUERY", "200"))
MAX_HTML_RESULTS = int(os.getenv("ARXIV_MAX_HTML_RESULTS", "50"))
# MAX_DOWNLOADS controls how many PDFs are actually fetched from arXiv.
# Default to MAX_HTML_RESULTS to keep them in sync; set to a larger value
# via ARXIV_MAX_DOWNLOADS if you want every filtered paper downloaded.
MAX_DOWNLOADS = int(os.getenv("ARXIV_MAX_DOWNLOADS", str(MAX_HTML_RESULTS)))
DOWNLOAD_WORKERS = int(os.getenv("ARXIV_DOWNLOAD_WORKERS", "4"))
QUERY_PAUSE_SECONDS = float(os.getenv("ARXIV_QUERY_PAUSE", "3.0"))
PDF_PAUSE_SECONDS = float(os.getenv("ARXIV_PDF_PAUSE", "0.5"))
MIN_SCORE = int(os.getenv("ARXIV_MIN_SCORE", "15"))

# Minimum file size (bytes) for a PDF to be considered fully downloaded.
# Smaller files are treated as incomplete / stub downloads.
PDF_MIN_SIZE = 10_000

# Broad + focused queries. Final filtering is done by date and score locally.
ARXIV_QUERIES = [
    'all:"federated learning"',
    'all:"federated learning" AND all:"edge"',
    'all:"federated learning" AND all:"6G"',
    'all:"federated learning" AND all:"heterogeneous"',
    'all:"federated learning" AND all:"non-IID"',
    'all:"federated learning" AND all:"adaptive aggregation"',
    'all:"federated learning" AND all:"client selection"',
    'all:"federated learning" AND all:"concept drift"',
    'all:"federated learning" AND all:"continual learning"',
    'all:"federated learning" AND all:"incremental learning"',
    'all:"federated learning" AND all:"online learning"',
    'all:"federated learning" AND all:"personalized"',
    'all:"federated learning" AND all:"resource allocation"',
    'all:"federated learning" AND all:"resource-aware"',
    'all:"federated learning" AND all:"split learning"',
    'all:"federated learning" AND all:"model heterogeneity"',
    'all:"federated learning" AND all:"self-adaptive"',
    'all:"federated learning" AND all:"autonomous"',
    'all:"federated learning" AND all:"zero-touch"',
    'all:"federated learning" AND all:"closed-loop"',
]

G1_TERMS = [
    "adaptive aggregation", "dynamic aggregation", "weighted aggregation", "aggregation",
    "client selection", "participant selection", "contribution", "reliability",
    "gradient divergence", "divergence", "robust aggregation", "asynchronous aggregation",
]
G2_TERMS = [
    "concept drift", "drift", "continual learning", "incremental learning",
    "online learning", "distribution shift", "non-stationary", "nonstationary",
    "catastrophic forgetting", "domain shift", "temporal",
]
G3_TERMS = [
    "personalized", "personalization", "personalised", "meta-learning", "meta learning",
    "model heterogeneity", "heterogeneous model", "local adaptation", "fine-tuning",
    "knowledge distillation", "split learning", "early exit", "prototype",
]
G4_TERMS = [
    "edge", "6g", "iot", "wireless", "uav", "vehicular", "mobile", "cloud-edge",
    "resource allocation", "resource management", "scheduling", "latency", "bandwidth",
    "energy", "communication-efficient", "compression", "straggler", "dropout",
    "self-adaptive", "autonomous", "autonomic", "closed-loop", "zero-touch", "self-evolving",
]
NEGATIVE_SOFT_TERMS = [
    "medical image", "skin lesion", "brain tumor", "histopathology", "credit scoring",
    "recommendation system", "sentiment", "fake news", "social bot", "agricultural",
]


@dataclass
class Paper:
    arxiv_id: str
    title: str
    summary: str
    authors: list[str]
    published: datetime
    updated: datetime
    categories: list[str]
    arxiv_url: str
    pdf_url: str
    score: int = 0
    objectives: list[str] = field(default_factory=list)
    domain: str = ""
    filename: str = ""
    downloaded: bool = False
    matched_queries: set[str] = field(default_factory=set)


def parse_arxiv_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def normalize_ws(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def arxiv_id_from_url(url: str) -> str:
    raw = url.rstrip("/").split("/")[-1]
    return raw.replace("v1", "").replace("v2", "").replace("v3", "")


def text_of(paper: Paper) -> str:
    return f"{paper.title} {paper.summary}".lower()


def any_term(text: str, terms: list[str]) -> bool:
    return any(term in text for term in terms)


def count_terms(text: str, terms: list[str]) -> int:
    return sum(1 for term in terms if term in text)


def score_paper(paper: Paper) -> tuple[int, list[str], str]:
    text = text_of(paper)
    title = paper.title.lower()
    score = 0
    objectives = []

    if "federated learning" in text or "federated" in text:
        score += 5
    else:
        return 0, [], "无关"
    if "federated learning" in title or "federated" in title:
        score += 2

    g1 = count_terms(text, G1_TERMS)
    g2 = count_terms(text, G2_TERMS)
    g3 = count_terms(text, G3_TERMS)
    g4 = count_terms(text, G4_TERMS)
    if g1:
        score += min(4, 2 + g1)
        objectives.append("G1")
    if g2:
        score += min(5, 2 + g2)
        objectives.append("G2")
    if g3:
        score += min(5, 2 + g3)
        objectives.append("G3")
    if g4:
        score += min(5, 2 + g4)
        objectives.append("G4")

    if any_term(text, ["heterogeneous", "heterogeneity", "non-iid", "non iid", "resource-constrained"]):
        score += 2
    if any_term(text, ["edge", "6g", "wireless", "iot", "uav", "vehicular"]):
        score += 2
    if any_term(text, ["self-adaptive", "autonomous", "closed-loop", "zero-touch", "self-evolving"]):
        score += 2
    if len(objectives) >= 2:
        score += 2
    if len(objectives) >= 3:
        score += 2
    if any_term(text, NEGATIVE_SOFT_TERMS) and len(objectives) <= 1:
        score -= 2

    domain = infer_domain(text, objectives)
    return score, objectives, domain


def infer_domain(text: str, objectives: list[str]) -> str:
    obj = set(objectives)
    if any_term(text, ["self-adaptive", "autonomous", "autonomic", "closed-loop", "zero-touch", "self-evolving"]):
        return "自治FL/闭环控制"
    if "G2" in obj:
        return "FL漂移/持续学习"
    if "G3" in obj:
        return "FL个性化/异构适配"
    if "G1" in obj:
        return "FL聚合/客户端选择"
    if any_term(text, ["edge", "6g", "iot", "wireless", "uav", "vehicular", "resource allocation", "scheduling"]):
        return "FL边缘/6G资源"
    return "FL综合"


def fetch_query(query: str) -> list[Paper]:
    params = {
        "search_query": query,
        "start": 0,
        "max_results": MAX_RESULTS_PER_QUERY,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    max_retries = 5
    for attempt in range(max_retries + 1):
        try:
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=45)
            if response.status_code == 200:
                return _parse_arxiv_response(response, query)
            elif response.status_code == 429:
                if attempt < max_retries:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait_time = float(retry_after) + random.random() * 3
                        except ValueError:
                            wait_time = 15 * (2 ** attempt) + random.random() * 5
                    else:
                        wait_time = 15 * (2 ** attempt) + random.random() * 5
                    wait_time = min(wait_time, 300)
                    print(f"    [arXiv] 429 限流，等待 {wait_time:.1f} 秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    [arXiv] 429 限流，已重试 {max_retries} 次，跳过本查询")
                    return []
            elif response.status_code >= 500:
                if attempt < max_retries:
                    wait_time = 3 * (2 ** attempt) + random.random() * 2
                    print(f"    [arXiv] 服务器错误 {response.status_code}，等待 {wait_time:.1f} 秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    [arXiv] 服务器错误 {response.status_code}，已重试 {max_retries} 次，跳过")
                    return []
            else:
                response.raise_for_status()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries:
                wait_time = 3 * (2 ** attempt) + random.random() * 2
                print(f"    [arXiv] 网络错误 ({type(e).__name__})，等待 {wait_time:.1f} 秒后重试 ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                print(f"    [arXiv] 网络错误，已重试 {max_retries} 次: {e}")
                return []
        except Exception as e:
            print(f"    [arXiv] 请求失败: {e}")
            return []
    return []


def _parse_arxiv_response(response: requests.Response, query: str) -> list[Paper]:
    """Parse a successful arXiv API response into Paper objects."""
    root = ET.fromstring(response.content)
    ns = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}
    papers: list[Paper] = []
    for entry in root.findall("atom:entry", ns):
        id_url = entry.findtext("atom:id", default="", namespaces=ns)
        arxiv_id = arxiv_id_from_url(id_url)
        title = normalize_ws(entry.findtext("atom:title", default="", namespaces=ns))
        summary = normalize_ws(entry.findtext("atom:summary", default="", namespaces=ns))
        published = parse_arxiv_date(entry.findtext("atom:published", namespaces=ns))
        updated = parse_arxiv_date(entry.findtext("atom:updated", namespaces=ns))
        authors = [normalize_ws(a.findtext("atom:name", default="", namespaces=ns)) for a in entry.findall("atom:author", ns)]
        categories = [cat.attrib.get("term", "") for cat in entry.findall("atom:category", ns)]
        pdf_url = f"https://export.arxiv.org/pdf/{arxiv_id}"
        for link in entry.findall("atom:link", ns):
            if link.attrib.get("title") == "pdf" or link.attrib.get("type") == "application/pdf":
                # Use export.arxiv.org for the actual download; arxiv.org/pdf may be
                # slower or hang behind some proxies, while export.arxiv.org is stable.
                pdf_url = f"https://export.arxiv.org/pdf/{arxiv_id}"
                break
        paper = Paper(
            arxiv_id=arxiv_id,
            title=title,
            summary=summary,
            authors=authors,
            published=published,
            updated=updated,
            categories=categories,
            arxiv_url=id_url,
            pdf_url=pdf_url,
        )
        paper.matched_queries.add(query)
        papers.append(paper)
    return papers


def dedupe(papers: list[Paper]) -> list[Paper]:
    by_id: dict[str, Paper] = {}
    for paper in papers:
        if paper.arxiv_id in by_id:
            by_id[paper.arxiv_id].matched_queries.update(paper.matched_queries)
        else:
            by_id[paper.arxiv_id] = paper
    return list(by_id.values())


def safe_filename(paper: Paper) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", paper.title.lower()).strip("_")[:90]
    date_part = paper.published.strftime("%Y%m%d")
    return f"{date_part}_{paper.arxiv_id.replace('/', '_')}_{slug}.pdf"


def download_pdf(paper: Paper) -> None:
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    filename = safe_filename(paper)
    path = PDF_DIR / filename
    paper.filename = filename
    if path.exists() and path.stat().st_size > PDF_MIN_SIZE:
        paper.downloaded = True
        return
    response = requests.get(paper.pdf_url, headers={"User-Agent": USER_AGENT}, timeout=20)
    response.raise_for_status()
    content_type = response.headers.get("content-type", "").lower()
    if "pdf" not in content_type and not response.content.startswith(b"%PDF"):
        raise RuntimeError(f"not a PDF response: {content_type}")
    path.write_bytes(response.content)
    paper.downloaded = True
    time.sleep(PDF_PAUSE_SECONDS)


def refresh_download_status(papers: list[Paper]) -> None:
    for paper in papers:
        if not paper.filename:
            paper.filename = safe_filename(paper)
        path = PDF_DIR / paper.filename
        if path.exists() and path.stat().st_size > PDF_MIN_SIZE:
            paper.downloaded = True


def rel_href(path: Path, base: Path = BASE_DIR) -> str:
    try:
        rel = os.path.relpath(path.resolve(), base.resolve())
    except Exception:
        rel = str(path)
    rel = rel.replace(os.sep, "/")
    return urllib.parse.quote(rel, safe="/:-_.()[]")


def build_html(papers: list[Paper], since: datetime) -> None:
    rows = []
    pdf_dir_label = rel_href(PDF_DIR, BASE_DIR)
    for paper in papers:
        local_link = rel_href(PDF_DIR / paper.filename, BASE_DIR) if paper.filename and paper.downloaded else ""
        pdf_cell = (
            f'<a href="{html.escape(local_link, quote=True)}" target="_blank">本地PDF</a> | '
            if local_link else ""
        ) + f'<a href="{html.escape(paper.pdf_url, quote=True)}" target="_blank">arXiv PDF</a>'
        objectives = ", ".join(paper.objectives)
        authors = html.escape(", ".join(paper.authors[:6]) + (" et al." if len(paper.authors) > 6 else ""))
        rows.append(
            f'<tr data-score="{paper.score}" data-date="{paper.published.date()}" data-domain="{html.escape(paper.domain, quote=True)}" '
            f'data-objectives="{html.escape(objectives, quote=True)}" data-title="{html.escape(paper.title.lower(), quote=True)}">'
            f'<td>{html.escape(paper.title)}</td><td>{paper.score}</td><td>{html.escape(paper.domain)}</td><td>{html.escape(objectives)}</td>'
            f'<td>{paper.published.date()}</td><td>{html.escape(", ".join(paper.categories))}</td><td>{authors}</td>'
            f'<td>{pdf_cell} | <a href="{html.escape(paper.arxiv_url, quote=True)}" target="_blank">摘要页</a></td>'
            f'<td>{html.escape(paper.summary[:520])}</td></tr>'
        )
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>近半年 arXiv 高相关论文</title>
<style>
  body {{ font-family: "Segoe UI", "PingFang SC", sans-serif; margin: 1rem 2rem; background: #101827; color: #eef2ff; }}
  h1 {{ font-size: 1.35rem; color: #7dd3fc; }}
  .meta {{ color: #94a3b8; margin: 0.35rem 0; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: end; margin: 1rem 0; padding: 0.8rem; background: #0f172a; border: 1px solid #334155; border-radius: 10px; }}
  .controls label {{ display: grid; gap: 0.25rem; color: #bae6fd; font-size: 0.82rem; }}
  select, input {{ min-width: 12rem; background: #111827; color: #eef2ff; border: 1px solid #475569; border-radius: 6px; padding: 0.45rem 0.55rem; }}
  .counter {{ color: #facc15; font-weight: bold; margin-left: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.88rem; }}
  th, td {{ border: 1px solid #334155; padding: 0.48rem 0.55rem; text-align: left; vertical-align: top; }}
  th {{ background: #172554; color: #bfdbfe; position: sticky; top: 0; z-index: 1; }}
  tr:nth-child(even) {{ background: #1e293b70; }}
  tr:hover {{ background: #0f3460; }}
  a {{ color: #fb7185; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  td:nth-child(1) {{ max-width: 24em; font-weight: 600; }}
  td:nth-child(9) {{ max-width: 34em; color: #cbd5e1; font-size: 0.84rem; }}
</style>
</head>
<body>
<h1>近半年 arXiv 高相关论文（{len(papers)} 篇）</h1>
<div class="meta">时间范围：{since.date()} 至 {datetime.now(timezone.utc).date()}；只保留 score&gt;={MIN_SCORE}、至少命中两个目标维度，且与自治/自适应 FL、6G/Edge、漂移、个性化、聚合、资源调度高度相关的论文。</div>
<div class="meta">PDF 下载目录：<code>{html.escape(pdf_dir_label)}</code></div>
<div class="controls">
  <label>领域筛选<select id="domainFilter"><option value="">全部领域</option></select></label>
  <label>目标筛选<select id="objectiveFilter"><option value="">全部目标</option><option value="G1">G1 聚合</option><option value="G2">G2 漂移</option><option value="G3">G3 个性化</option><option value="G4">G4 自治/系统</option></select></label>
  <label>排序方式<select id="sortSelect"><option value="score-desc">评分从高到低</option><option value="date-desc">日期从新到旧</option><option value="domain-score">领域 → 评分</option></select></label>
  <label>标题搜索<input id="searchBox" placeholder="输入关键词"></label>
  <span class="counter">显示 <span id="visibleCount">{len(papers)}</span> / {len(papers)}</span>
</div>
<table id="paperTable">
<thead><tr><th>标题</th><th>评分</th><th>领域</th><th>目标</th><th>发布日期</th><th>类别</th><th>作者</th><th>链接</th><th>摘要</th></tr></thead>
<tbody>
{chr(10).join(rows)}
</tbody>
</table>
<script>
(function() {{
  const tbody = document.querySelector('#paperTable tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const domainFilter = document.getElementById('domainFilter');
  const objectiveFilter = document.getElementById('objectiveFilter');
  const sortSelect = document.getElementById('sortSelect');
  const searchBox = document.getElementById('searchBox');
  const visibleCount = document.getElementById('visibleCount');
  Array.from(new Set(rows.map(r => r.dataset.domain).filter(Boolean))).sort((a,b)=>a.localeCompare(b,'zh-Hans-CN')).forEach(v => {{
    const o = document.createElement('option'); o.value = v; o.textContent = v; domainFilter.appendChild(o);
  }});
  function cmp(a,b) {{
    if (sortSelect.value === 'date-desc') return b.dataset.date.localeCompare(a.dataset.date) || Number(b.dataset.score)-Number(a.dataset.score);
    if (sortSelect.value === 'domain-score') return a.dataset.domain.localeCompare(b.dataset.domain,'zh-Hans-CN') || Number(b.dataset.score)-Number(a.dataset.score);
    return Number(b.dataset.score)-Number(a.dataset.score) || b.dataset.date.localeCompare(a.dataset.date);
  }}
  function apply() {{
    const d = domainFilter.value, o = objectiveFilter.value, kw = searchBox.value.trim().toLowerCase();
    const visible = rows.filter(r => !d || r.dataset.domain === d)
      .filter(r => !o || (r.dataset.objectives || '').includes(o))
      .filter(r => !kw || (r.dataset.title || '').includes(kw))
      .sort(cmp);
    tbody.innerHTML = ''; visible.forEach(r => tbody.appendChild(r)); visibleCount.textContent = visible.length;
  }}
  [domainFilter, objectiveFilter, sortSelect, searchBox].forEach(el => el.addEventListener('input', apply));
  apply();
}})();
</script>
</body>
</html>"""
    HTML_PATH.write_text(html_content, encoding="utf-8")


def write_csv(papers: list[Paper]) -> None:
    fields = ["标题", "作者", "年份", "日期", "类别", "评分", "领域", "核心目标", "本地PDF", "PDF直链", "论文页", "摘要"]
    with CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            local_pdf = rel_href(PDF_DIR / paper.filename, BASE_DIR) if paper.filename and paper.downloaded else ""
            writer.writerow({
                "标题": paper.title,
                "作者": ", ".join(paper.authors),
                "年份": str(paper.published.year),
                "日期": str(paper.published.date()),
                "类别": ", ".join(paper.categories),
                "评分": str(paper.score),
                "领域": paper.domain,
                "核心目标": ", ".join(paper.objectives),
                "本地PDF": local_pdf,
                "PDF直链": paper.pdf_url,
                "论文页": paper.arxiv_url,
                "摘要": paper.summary,
            })


def main() -> None:
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=SINCE_DAYS)
    all_papers: list[Paper] = []
    print(f"[arXiv] since={since.date()} queries={len(ARXIV_QUERIES)}")
    for i, query in enumerate(ARXIV_QUERIES, 1):
        print(f"[{i}/{len(ARXIV_QUERIES)}] {query}")
        try:
            papers = fetch_query(query)
            all_papers.extend(papers)
            print(f"  fetched={len(papers)}")
        except Exception as exc:
            print(f"  failed: {exc}")
        time.sleep(QUERY_PAUSE_SECONDS)

    papers = []
    for paper in dedupe(all_papers):
        if paper.published < since:
            continue
        paper.score, paper.objectives, paper.domain = score_paper(paper)
        has_core_objective = bool(set(paper.objectives) & {"G1", "G2", "G3"})
        is_autonomous_fl = paper.domain == "自治FL/闭环控制"
        if (
            paper.score >= MIN_SCORE
            and len(paper.objectives) >= 2
            and (has_core_objective or is_autonomous_fl)
        ):
            papers.append(paper)
    papers.sort(key=lambda p: (-p.score, -p.published.timestamp(), p.title))
    print(f"[filter] kept={len(papers)} min_score={MIN_SCORE}")

    to_download = papers[:MAX_DOWNLOADS]
    refresh_download_status(papers)
    pending = [paper for paper in to_download if not paper.downloaded]
    if pending:
        print(f"[pdf] downloading {len(pending)} files with workers={DOWNLOAD_WORKERS}")
    with ThreadPoolExecutor(max_workers=max(1, DOWNLOAD_WORKERS)) as pool:
        futures = {pool.submit(download_pdf, paper): paper for paper in pending}
        for i, future in enumerate(as_completed(futures), 1):
            paper = futures[future]
            try:
                future.result()
                print(f"[pdf {i}/{len(pending)}] ok {paper.arxiv_id} {paper.title[:80]}")
            except Exception as exc:
                print(f"[pdf {i}/{len(pending)}] failed {paper.arxiv_id}: {exc}")
    for paper in papers[MAX_DOWNLOADS:]:
        paper.filename = safe_filename(paper)
    refresh_download_status(papers)

    build_html(papers, since)
    write_csv(papers)
    print(f"[done] html={HTML_PATH}")
    print(f"[done] csv={CSV_PATH}")
    print(f"[done] pdf_dir={PDF_DIR} downloaded={sum(1 for p in papers if p.downloaded)}/{len(papers)}")


if __name__ == "__main__":
    main()
