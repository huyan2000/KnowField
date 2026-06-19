#!/usr/bin/env python3
"""Build the single user-facing paper-search report.

The crawler still uses a few generated intermediate files internally, but the
public workflow keeps one HTML dashboard and one normalized CSV.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import sys
import urllib.parse
from datetime import datetime
from pathlib import Path

from utils.paths import find_pdf_root
from pdf_ops.dedup import dedup_pdfs

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)
BROKEN_DIRECT_HOSTS = {"www-03.ibm.com", "www.cs.cmu.edu"}

MAIN_CSV = "papers_search_results_downloadable.csv"
ARXIV_CSV = "arxiv_latest_half_year.csv"
ARXIV_HTML = "arxiv_latest_half_year.html"
OUTPUT_HTML = "paper_search_report.html"
OUTPUT_CSV = "paper_search_report.csv"
DOWNLOADED = {"exists", "downloaded"}

# Minimum file size (bytes) for a PDF to be considered valid; smaller files
# are treated as stub/placeholder entries and are cleared from the report.
PDF_MIN_SIZE = 10_000

FIELDS = [
    "来源",
    "标题",
    "作者",
    "年份",
    "日期",
    "出处或类别",
    "评分",
    "领域",
    "轨道",
    "核心目标",
    "下载状态",
    "是否未下载",
    "本地PDF",
    "内容已检测",
    "PDF直链",
    "论文页",
    "DOI",
    "摘要",
]


def h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def strip_tags(value: str) -> str:
    value = re.sub(r"<script.*?</script>", "", value or "", flags=re.S | re.I)
    value = re.sub(r"<style.*?</style>", "", value, flags=re.S | re.I)
    value = re.sub(r"<[^>]+>", " ", value)
    return html.unescape(re.sub(r"\s+", " ", value).strip())


def norm_title(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def load_s2_metadata(cache_dir: Path) -> dict[str, dict[str, str]]:
    """Load optional local S2 metadata if the cache exists."""
    out: dict[str, dict[str, str]] = {}
    if not cache_dir.exists():
        return out
    for path in cache_dir.glob("*.json"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            key = norm_title(item.get("title") or "")
            if not key or key in out:
                continue
            oa = item.get("openAccessPdf") or {}
            disclaimer = oa.get("disclaimer") if isinstance(oa, dict) else ""
            doi = doi_from_text(disclaimer or "")
            out[key] = {
                "s2_url": item.get("url") or "",
                "doi": doi,
                "doi_url": f"https://doi.org/{doi}" if doi else "",
                "oa_url": (oa.get("url") or "") if isinstance(oa, dict) else "",
                "oa_status": (oa.get("status") or "") if isinstance(oa, dict) else "",
            }
    return out


def doi_from_text(text: str) -> str:
    from re import search as _search
    m = _search(r"10\.\d{4,}/[^\s\)\]}>]+", text or "")
    return m.group(0) if m else ""


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def as_int(value: str, default: int = 0) -> int:
    try:
        return int(float(str(value or "").strip()))
    except Exception:
        return default


def status_label(status: str) -> str:
    labels = {
        "exists": "本地已有",
        "downloaded": "本地已有",
        "open_pdf_available": "有PDF未保存",
        "missing": "未下载",
    }
    return labels.get(status or "", status or "未确认")


def is_missing(status: str) -> str:
    return "否" if status in DOWNLOADED else "是"




def normalize_arxiv_row(row: dict[str, str]) -> dict[str, str]:
    local_pdf = row.get("本地PDF", "")
    status = "exists" if local_pdf else "open_pdf_available"
    date = row.get("日期", "")
    return {
        "来源": "arXivLatest",
        "标题": row.get("标题", ""),
        "作者": row.get("作者", ""),
        "年份": row.get("年份") or date[:4],
        "日期": date,
        "出处或类别": row.get("类别", ""),
        "评分": row.get("评分", ""),
        "领域": row.get("领域", ""),
        "轨道": "arXiv latest",
        "核心目标": row.get("核心目标", ""),
        "下载状态": status,
        "是否未下载": is_missing(status),
        "本地PDF": local_pdf,
        "内容已检测": row.get("内容已检测", ""),
        "PDF直链": row.get("PDF直链", ""),
        "论文页": row.get("论文页", ""),
        "DOI": "",
        "摘要": row.get("摘要", ""),
    }


def attr(attrs: str, name: str) -> str:
    m = re.search(rf'{name}="([^"]*)"', attrs or "")
    return html.unescape(m.group(1)) if m else ""


def parse_arxiv_html(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    rows: list[dict[str, str]] = []
    for attrs, body in re.findall(r"<tr\s+([^>]*)>(.*?)</tr>", text, flags=re.S | re.I):
        cells = re.findall(r"<td>(.*?)</td>", body, flags=re.S | re.I)
        if len(cells) < 9:
            continue
        links = re.findall(r'href="([^"]+)"', cells[7])
        local_pdf = next((html.unescape(x) for x in links if "arxiv_latest_papers" in x), "")
        pdf_url = next((html.unescape(x) for x in links if "export.arxiv.org/pdf" in x), "")
        paper_url = next((html.unescape(x) for x in links if "/abs/" in x), "")
        date = attr(attrs, "data-date") or strip_tags(cells[4])
        rows.append({
            "标题": strip_tags(cells[0]),
            "作者": strip_tags(cells[6]),
            "年份": date[:4],
            "日期": date,
            "类别": strip_tags(cells[5]),
            "评分": attr(attrs, "data-score") or strip_tags(cells[1]),
            "领域": attr(attrs, "data-domain") or strip_tags(cells[2]),
            "核心目标": attr(attrs, "data-objectives") or strip_tags(cells[3]),
            "本地PDF": local_pdf,
            "PDF直链": pdf_url,
            "论文页": paper_url,
            "摘要": strip_tags(cells[8]),
        })
    return rows


def load_arxiv_rows(base: Path) -> list[dict[str, str]]:
    rows = read_csv(base / ARXIV_CSV)
    if not rows:
        rows = parse_arxiv_html(base / ARXIV_HTML)
    return [normalize_arxiv_row(r) for r in rows]


def resolve_report_path(value: str, base: Path) -> Path | None:
    if not value:
        return None
    raw = urllib.parse.unquote(value)
    path = Path(raw)
    if not path.is_absolute():
        path = base / path
    try:
        return path.resolve()
    except OSError:
        return None


def local_pdf_stats(rows: list[dict[str, str]], base: Path) -> dict[str, int | str]:
    folder = find_pdf_root(base.parent)
    pdfs = sorted(folder.rglob("*.pdf")) if folder.exists() else []
    linked: set[Path] = set()
    for row in rows:
        path = resolve_report_path(row.get("本地PDF", ""), base)
        if path and path.exists():
            linked.add(path)
    arxiv = 0
    for path in pdfs:
        try:
            if "arxiv_latest_papers" in path.relative_to(folder).parts:
                arxiv += 1
        except ValueError:
            pass
    return {
        "folder": str(folder),
        "total": len(pdfs),
        "linked": len(linked),
        "folder_only": max(len(pdfs) - len(linked), 0),
        "arxiv": arxiv,
    }


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def link(label: str, url: str, css: str = "") -> str:
    if not url:
        return ""
    cls = f' class="{css}"' if css else ""
    return f'<a{cls} href="{h(url)}" target="_blank" rel="noopener">{h(label)}</a>'


def build_rows_html(rows: list[dict[str, str]]) -> str:
    out = []
    for idx, row in enumerate(rows, start=1):
        status = row.get("下载状态", "")
        missing = row.get("是否未下载") == "是"

        # ── PDF / Open-PDF action link ──────────────────────────────────────
        # "exists" → bold primary label with paper title (not just "PDF")
        # "open_pdf_available" → amber label with paper title + remote link
        # "missing" → no local-PDF link, only "Page"
        local_url  = row.get("本地PDF", "")
        remote_url = row.get("PDF直链", "")
        page_url   = row.get("论文页", "") or row.get("页面链接", "")
        paper_title = row.get("标题", "")

        if status == "exists" and local_url:
            pdf_label = paper_title if paper_title else "本地 PDF"
            action = link(pdf_label, local_url, "primary")
        elif status == "open_pdf_available" and remote_url:
            pdf_label = "Open PDF"
            action    = link(pdf_label, remote_url, "primary")
        else:
            action = ""

        # ghost Page link always shown
        page_link = link("Page", page_url, "ghost") if page_url else ""

        # direct download label for rows with a real PDF but no remote link
        out.append(
            f'<tr data-source="{h(row["来源"])}" data-missing="{str(missing).lower()}" '
            f'data-domain="{h(row["领域"])}" data-status="{h(status)}" '
            f'data-score="{h(row["评分"])}" data-year="{h(row["年份"])}" '
            f'data-title="{h((row["标题"] + " " + row["摘要"]).lower())}" '
            f'data-content-checked="{h(row.get("内容已检测", ""))}">'
            f'<td class="idx">{idx}</td>'
            f'<td class="title"><span>{h(row["标题"])}</span><small>{h(row["作者"])}</small></td>'
            f'<td><span class="source">{h(row["来源"])}</span></td>'
            f'<td>{h(row["评分"])}</td>'
            f'<td>{h(row["年份"] or row["日期"])}</td>'
            f'<td>{h(row["领域"])}</td>'
            f'<td>{h(row["核心目标"])}</td>'
            f'<td><span class="pill {h(status)}">{h(status_label(status))}</span></td>'
            f'<td class="links">{action} {page_link}</td>'
            f'<td class="abstract">{h(row["摘要"][:520])}</td>'
            '</tr>'
        )
    return "\n".join(out)


def build_html(rows: list[dict[str, str]], path: Path) -> None:
    base = path.parent
    pdf_stats = local_pdf_stats(rows, base)
    domains = sorted({r["领域"] for r in rows if r.get("领域")})
    statuses = sorted({r["下载状态"] for r in rows if r.get("下载状态")})
    content_checked_vals = sorted({r.get("内容已检测", "") for r in rows})
    content_checked_count = sum(1 for r in rows if r.get("内容已检测") == "是")
    main_count = sum(1 for r in rows if r["来源"] == "TopVenue")
    arxiv_count = sum(1 for r in rows if r["来源"] == "arXivLatest")
    missing_count = sum(1 for r in rows if r["来源"] == "TopVenue" and r["是否未下载"] == "是")
    local_count = sum(1 for r in rows if r["来源"] == "TopVenue" and r["下载状态"] in DOWNLOADED)
    downloaded_count = sum(1 for r in rows if r.get("下载状态") == "exists" or r.get("下载状态") == "downloaded")
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    domain_options = "".join(f'<option value="{h(x)}">{h(x)}</option>' for x in domains)
    status_options = "".join(f'<option value="{h(x)}">{h(status_label(x))}</option>' for x in statuses)
    cc_opts = ["是", "否"]
    cc_options = "".join(f'<option value="{h(v)}">{h("已检测" if v == "是" else "未检测" if v == "否" else "全部")}</option>' for v in cc_opts)
    content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Paper Radar</title>
<style>
:root {{
  --bg:#0b0f14; --panel:#101820; --panel2:#121c26; --line:#263241; --text:#d7e1ea;
  --muted:#7e8b99; --cyan:#48d1cc; --amber:#f7b955; --green:#55d98b; --red:#ff6b6b;
}}
* {{ box-sizing:border-box; }}
body {{ margin:0; background:radial-gradient(circle at top left,#142233 0,#0b0f14 36rem),var(--bg); color:var(--text); font-family:"Aptos","Segoe UI",sans-serif; }}
body:before {{ content:""; position:fixed; inset:0; pointer-events:none; background-image:linear-gradient(rgba(255,255,255,.035) 1px,transparent 1px),linear-gradient(90deg,rgba(255,255,255,.035) 1px,transparent 1px); background-size:32px 32px; mask-image:linear-gradient(#000,transparent 78%); }}
header {{ padding:28px 32px 14px; border-bottom:1px solid var(--line); background:rgba(11,15,20,.82); backdrop-filter:blur(12px); position:sticky; top:0; z-index:5; }}
h1 {{ margin:0; font-size:24px; letter-spacing:.02em; }}
.kicker {{ color:var(--cyan); font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; font-size:12px; text-transform:uppercase; letter-spacing:.16em; }}
.sub {{ margin-top:8px; color:var(--muted); font-size:13px; }}
main {{ padding:22px 32px 36px; }}
.cards {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:12px; margin-bottom:16px; }}
.card {{ background:linear-gradient(180deg,var(--panel),#0d141b); border:1px solid var(--line); border-radius:14px; padding:14px; box-shadow:0 12px 30px rgba(0,0,0,.22); }}
.card b {{ display:block; font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; font-size:22px; color:#fff; }}
.card span {{ color:var(--muted); font-size:12px; }}
.toolbar {{ display:flex; flex-wrap:wrap; gap:10px; align-items:end; background:rgba(16,24,32,.92); border:1px solid var(--line); border-radius:16px; padding:14px; margin-bottom:14px; }}
.tabs {{ display:flex; gap:8px; margin-right:8px; }}
button,select,input {{ background:#0d141b; color:var(--text); border:1px solid var(--line); border-radius:10px; padding:9px 10px; font:13px "JetBrains Mono","SFMono-Regular",Menlo,monospace; }}
button {{ cursor:pointer; color:var(--muted); }}
button.active {{ color:#001014; background:var(--cyan); border-color:var(--cyan); }}
label {{ display:grid; gap:5px; color:var(--muted); font-size:11px; font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; text-transform:uppercase; }}
input {{ min-width:280px; }}
.table-wrap {{ overflow:auto; border:1px solid var(--line); border-radius:16px; background:rgba(13,20,27,.88); }}
table {{ width:100%; border-collapse:separate; border-spacing:0; font-size:13px; }}
th {{ position:sticky; top:0; background:#111c26; color:#9fb3c8; text-align:left; padding:10px; border-bottom:1px solid var(--line); font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; font-size:11px; text-transform:uppercase; z-index:2; }}
td {{ padding:10px; border-bottom:1px solid rgba(38,50,65,.7); vertical-align:top; }}
tr:hover {{ background:#132334; }}
.idx {{ color:var(--muted); font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; }}
.title span {{ display:block; min-width:280px; max-width:460px; font-weight:650; color:#eef6ff; }}
.title small {{ display:block; color:var(--muted); margin-top:5px; max-width:460px; }}
.abstract {{ color:#aab8c6; max-width:520px; line-height:1.45; }}
.source {{ font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; color:var(--cyan); }}
.pill {{ display:inline-flex; white-space:nowrap; border-radius:999px; padding:4px 8px; font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; font-size:11px; background:#1b2835; color:#b7c5d4; border:1px solid var(--line); }}
.pill.exists,.pill.downloaded {{ color:var(--green); border-color:rgba(85,217,139,.35); }}
.pill.missing {{ color:var(--red); border-color:rgba(255,107,107,.35); }}
.pill.open_pdf_available {{ color:var(--amber); border-color:rgba(247,185,85,.35); }}
a {{ color:var(--cyan); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
a.primary,a.secondary,a.ghost {{ display:inline-block; margin:0 4px 4px 0; padding:5px 8px; border-radius:8px; font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; font-size:11px; border:1px solid var(--line); }}
a.primary {{ background:rgba(72,209,204,.12); border-color:rgba(72,209,204,.45); }}
a.secondary {{ color:var(--amber); }}
a.ghost {{ color:#8ea2b6; }}
.footer {{ margin-top:12px; color:var(--muted); font-family:"JetBrains Mono","SFMono-Regular",Menlo,monospace; font-size:11px; }}
@media (max-width:900px) {{ header,main {{ padding-left:14px; padding-right:14px; }} .cards {{ grid-template-columns:repeat(2,1fr); }} input {{ min-width:100%; }} }}
</style>
</head>
<body>
<header>
  <div class="kicker">KNOWFIELD PAPER RADAR</div>
  <h1>Federated + Autonomous Edge Systems</h1>
  <div class="sub">Single dashboard from TopVenue, arXivLatest and local PDF state · updated {h(now)}</div>
</header>
<main>
  <section class="cards">
    <div class="card"><b>{len(rows)}</b><span>论文总数</span></div>
    <div class="card"><b>{downloaded_count}</b><span>已下载 PDF</span></div>
    <div class="card"><b>{missing_count}</b><span>待下载</span></div>
  </section>
  <section class="toolbar">
    <div class="tabs">
      <button class="active" data-view="all">All</button>
      <button data-view="TopVenue">TopVenue</button>
      <button data-view="arXivLatest">arXiv</button>
      <button data-view="missing">Missing</button>
    </div>
    <label>Domain<select id="domain"><option value="">All domains</option>{domain_options}</select></label>
    <label>Status<select id="status"><option value="">All status</option>{status_options}</select></label>
    <label>Content checked<select id="cc"><option value="">All</option>{cc_options}</select></label>
    <label>Sort<select id="sort"><option value="score-desc">Score desc</option><option value="year-desc">Year desc</option><option value="source-score">Source + score</option></select></label>
    <label>Search<input id="search" placeholder="title / abstract / method"></label>
    <div class="footer">showing <span id="count">{len(rows)}</span> / {len(rows)}</div>
  </section>
  <section class="table-wrap">
    <table id="papers">
      <thead><tr><th>#</th><th>Title</th><th>Source</th><th>Score</th><th>Year</th><th>Domain</th><th>Goal</th><th>Status</th><th>Links</th><th>Abstract</th></tr></thead>
      <tbody>
{build_rows_html(rows)}
      </tbody>
    </table>
  </section>
  <div class="footer">PDF source of truth: <code>../PHD-Buyya/</code>. Auto-counted recursively from <code>{h(pdf_stats["folder"])}</code>; arXiv subfolder PDFs: <code>{pdf_stats["arxiv"]}</code>.</div>
</main>
<script>
(function() {{
  const tbody = document.querySelector('#papers tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const tabs = Array.from(document.querySelectorAll('button[data-view]'));
  const domain = document.getElementById('domain');
  const status = document.getElementById('status');
  const cc = document.getElementById('cc');
  const sort = document.getElementById('sort');
  const search = document.getElementById('search');
  const count = document.getElementById('count');
  let view = 'all';
  function cmp(a,b) {{
    if (sort.value === 'year-desc') return (b.dataset.year||'').localeCompare(a.dataset.year||'') || Number(b.dataset.score||0)-Number(a.dataset.score||0);
    if (sort.value === 'source-score') return (a.dataset.source||'').localeCompare(b.dataset.source||'') || Number(b.dataset.score||0)-Number(a.dataset.score||0);
    return Number(b.dataset.score||0)-Number(a.dataset.score||0) || (b.dataset.year||'').localeCompare(a.dataset.year||'');
  }}
  function apply() {{
    const kw = search.value.trim().toLowerCase();
    const visible = rows.filter(r => view === 'all' || (view === 'missing' ? r.dataset.missing === 'true' && r.dataset.source === 'TopVenue' : r.dataset.source === view))
      .filter(r => !domain.value || r.dataset.domain === domain.value)
      .filter(r => !status.value || r.dataset.status === status.value)
      .filter(r => !cc.value || (r.dataset.contentChecked || '') === cc.value)
      .filter(r => !kw || (r.dataset.title || '').includes(kw))
      .sort(cmp);
    tbody.innerHTML = ''; visible.forEach(r => tbody.appendChild(r)); count.textContent = visible.length;
  }}
  tabs.forEach(btn => btn.addEventListener('click', () => {{ tabs.forEach(x => x.classList.remove('active')); btn.classList.add('active'); view = btn.dataset.view; apply(); }}));
  [domain,status,cc,sort,search].forEach(el => el.addEventListener('input', apply));
  apply();
}})();
</script>
</body>
</html>
"""
    path.write_text(content, encoding="utf-8")


def norm_local_pdf_path(row: dict[str, str], base: Path) -> None:
    """Resolve *local_pdf* to an absolute path … and clear it if the file is a stub.

    Handles two cases:
    - Stale relative paths (e.g. '../../PHD-Buyya/…') that survived from a previous run
      via bootstrap_from_report.
    - Zero-byte stub files (e.g. b8ba7bd2.pdf placeholders) that technically exist on
      disk but are too small to be real PDFs (threshold: 10 KB, matching the same gate
      used in sync_and_build.update_download_status).
    """
    lp = row.get("本地PDF", "").strip()
    if not lp:
        return
    resolved = resolve_report_path(lp, base)
    if resolved and resolved.exists():
        # Keep absolute path only if the file is a real PDF (≥ PDF_MIN_SIZE)
        try:
            if resolved.stat().st_size < PDF_MIN_SIZE:
                row["本地PDF"] = ""
                return
        except OSError:
            pass
        row["本地PDF"] = str(resolved)
    else:
        # Path does not exist at all — clear it so the HTML row doesn't show a dead link
        row["本地PDF"] = ""


def build(base: Path | None = None) -> tuple[Path, Path, int]:
    base = base or Path(__file__).resolve().parents[1]
    meta_index = load_s2_metadata(base / ".s2_cache")
    main_rows: list[dict[str, str]] = []
    for r in read_csv(base / MAIN_CSV):
        status = r.get("下载状态", "") or "missing"
        # Collect landing page from multiple possible column names for backward compatibility.
        landing = (
            r.get("正确论文页", "")
            or r.get("论文页", "")
            or r.get("原始链接", "")
        )
        # If still empty but DOI exists in the row, use the DOI resolver as a last-resort link.
        if not landing:
            doi = (r.get("DOI") or "").strip()
            if doi:
                landing = f"https://doi.org/{doi}"
        # Finally try S2 cache for title match.
        if not landing:
            meta = meta_index.get(norm_title(r.get("标题") or ""), {})
            if meta.get("doi_url"):
                landing = meta["doi_url"]
            elif meta.get("oa_url"):
                landing = meta["oa_url"]
        norm_local_pdf_path(r, base)
        main_rows.append({
            "来源": "TopVenue",
            "标题": r.get("标题", ""),
            "作者": r.get("作者", ""),
            "年份": r.get("年份", ""),
            "日期": r.get("年份", ""),
            "出处或类别": r.get("出处", ""),
            "评分": r.get("评分", ""),
            "领域": r.get("领域", ""),
            "轨道": r.get("轨道", ""),
            "核心目标": r.get("核心目标", ""),
            "下载状态": status,
            "是否未下载": is_missing(status),
            "本地PDF": r.get("本地PDF", ""),
            "内容已检测": r.get("内容已检测", ""),
            "PDF直链": r.get("PDF直链", ""),
            "论文页": landing,
            "DOI": r.get("DOI", ""),
            "摘要": r.get("摘要", ""),
        })

    arxiv_rows = load_arxiv_rows(base)
    rows = main_rows + arxiv_rows
    rows.sort(key=lambda r: (r["来源"] != "TopVenue", -as_int(r["评分"]), -(as_int(r["年份"]))))
    csv_path = base / OUTPUT_CSV
    html_path = base / OUTPUT_HTML
    write_csv(rows, csv_path)
    build_html(rows, html_path)
    return html_path, csv_path, len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the unified paper-search report dashboard.")
    parser.add_argument("--dedup", action="store_true",
                        help="Run PDF deduplication on PHD-Buyya/ after building the report")
    parser.add_argument("--dry-run-dedup", action="store_true",
                        help="Simulate PDF deduplication without deleting any files")
    args = parser.parse_args(argv)

    html_path, csv_path, count = build()
    print(f"Wrote {html_path}")
    print(f"Wrote {csv_path}")
    print(f"Unified rows: {count}")

    # PDF 重复检测与去重（可选）
    if args.dedup or args.dry_run_dedup:
        dry = args.dry_run_dedup and not args.dedup
        repo = Path(__file__).resolve().parents[1]
        pdf_root = find_pdf_root(repo)
        stats = dedup_pdfs(pdf_root, dry_run=dry)
        print(f"\n[dedup] {'dry-run' if dry else 'done'}")
        print(f"  重复组: {stats['dup_groups']} 组，"
              f"副本: {stats['to_delete']} 个")
        print(f"  删除: {stats['deleted']}，失败: {stats['fail']}")
        print(f"  PHD-Buyya 剩余: {stats['total_after']} 个 PDF")
        if stats["dup_groups"] and not dry:
            print("  ⚠  已删除副本，相关报告条目本地PDF路径可能需要刷新")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
