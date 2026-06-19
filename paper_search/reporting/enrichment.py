#!/usr/bin/env python3
"""Build the enriched downloadable report CSV and its companion HTML.

This script does **not** download papers.  It reads the raw crawler CSV,
enriches it with S2 cache data, corrects broken landing-page
links, and produces two deliverables:

* ``papers_search_results_downloadable.csv`` – one row per paper, enriched
* ``papers_search_results.html``            – a browser-viewable summary table
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import re
import urllib.parse
from pathlib import Path

DOI_RE = re.compile(r"10\.\d{4,9}/[^\s\"'<>]+", re.I)
BROKEN_DIRECT_HOSTS = {"www-03.ibm.com", "www.cs.cmu.edu"}

# Minimum file size (bytes) for a local PDF file to be considered valid.
PDF_MIN_SIZE = 10_000


def h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def norm_title(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def clean_doi(doi: str) -> str:
    doi = html.unescape((doi or "").strip())
    doi = doi.removeprefix("doi:").removeprefix("DOI:").strip()
    doi = doi.split("?", 1)[0].split("#", 1)[0]
    return doi.rstrip(".,;:)]}>")


def doi_from_text(text: str) -> str:
    match = DOI_RE.search(text or "")
    return clean_doi(match.group(0)) if match else ""


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def local_pdf_exists(local_pdf: str, base: Path) -> bool:
    if not local_pdf:
        return False
    path = Path(local_pdf)
    if not path.is_absolute():
        path = base / path
    try:
        return path.exists() and path.stat().st_size > PDF_MIN_SIZE
    except OSError:
        return False


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


def host(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def corrected_landing(row: dict[str, str], meta: dict[str, str]) -> tuple[str, str]:
    original = row.get("链接") or ""
    original_host = host(original)
    if original_host in BROKEN_DIRECT_HOSTS:
        if meta.get("doi_url"):
            return meta["doi_url"], "修正为 DOI 页面"
        if meta.get("s2_url"):
            return meta["s2_url"], "原始直链疑似失效，改为 S2 页面"
    if original_host == "www.semanticscholar.org" and meta.get("doi_url"):
        return meta["doi_url"], "修正为 DOI/出版商页面"
    if original:
        return original, "原始页面"
    if meta.get("doi_url"):
        return meta["doi_url"], "补全 DOI 页面"
    if meta.get("s2_url"):
        return meta["s2_url"], "补全 S2 页面"
    # Fallback: use the DOI field from the row itself if available.
    row_doi = (row.get("DOI") or "").strip()
    if row_doi:
        return f"https://doi.org/{row_doi}", "补全 DOI 页面"
    return "", "无链接"


def status_note(status: str) -> str:
    notes = {
        "downloaded": "已下载到本地",
        "exists": "本地已有PDF",
        "open_pdf_available": "有公开PDF链接，尚未本地保存",
        "missing": "本地未下载",
    }
    return notes.get(status, status or "本地未下载")


def action_link(text: str, href: str, css: str = "") -> str:
    if not href:
        return ""
    cls = f' class="{h(css)}"' if css else ""
    return f'<a{cls} href="{h(href)}" target="_blank" rel="noopener">{h(text)}</a>'


def best_action(local_pdf: str, pdf_url: str, landing_url: str) -> str:
    if local_pdf:
        return action_link("本地PDF", local_pdf, "primary")
    if pdf_url:
        return action_link("PDF链接", pdf_url, "primary")
    if landing_url:
        return action_link("论文页", landing_url, "secondary")
    return ""


def infer_initial_status(local_pdf: str, pdf_url: str) -> str:
    if local_pdf:
        return "downloaded"
    if pdf_url:
        return "open_pdf_available"
    return "missing"


def build(args: argparse.Namespace) -> None:
    base = Path(__file__).resolve().parents[1]
    input_csv = Path(args.input)
    if not input_csv.is_absolute():
        input_csv = base / input_csv
    out_html = Path(args.output)
    if not out_html.is_absolute():
        out_html = base / out_html
    out_csv = Path(args.output_csv)
    if not out_csv.is_absolute():
        out_csv = base / out_csv

    rows = load_csv(input_csv)
    meta_index = load_s2_metadata(base / ".s2_cache")
    previous_by_title: dict[str, dict[str, str]] = {}
    if out_csv.exists():
        try:
            previous_by_title = {norm_title(r.get("标题") or ""): r for r in load_csv(out_csv) if r.get("标题")}
        except Exception:
            previous_by_title = {}

    enriched: list[dict[str, str]] = []
    for idx, row in enumerate(rows, start=1):
        meta = meta_index.get(norm_title(row.get("标题") or ""), {})
        previous = previous_by_title.get(norm_title(row.get("标题") or ""), {})
        landing, landing_reason = corrected_landing(row, meta)
        local = ""
        old_local = previous.get("本地PDF", "")
        if local_pdf_exists(old_local, base):
            local = old_local
        pdf = meta.get("oa_url", "")
        status = previous.get("下载状态", "") if local else infer_initial_status(local, pdf)
        if local and status not in {"downloaded", "exists"}:
            status = "downloaded"
        enriched.append({
            "序号": str(idx),
            "标题": row.get("标题", ""),
            "作者": row.get("作者", ""),
            "年份": row.get("年份", ""),
            "出处": row.get("出处", ""),
            "引用数": row.get("引用数", ""),
            "评分": row.get("评分", ""),
            "轨道": row.get("轨道", ""),
            "领域": row.get("领域", ""),
            "核心目标": row.get("核心目标", ""),
            "是否顶会顶刊": row.get("是否顶会顶刊", ""),
            "摘要": row.get("摘要", ""),
            "下载状态": status,
            "下载说明": previous.get("下载说明", "") if local else status_note(status),
            "内容已检测": previous.get("内容已检测", ""),
            "本地PDF": local,
            "PDF直链": pdf,
            "正确论文页": landing,
            "链接修正说明": landing_reason,
            "原始链接": row.get("链接", ""),
            "DOI": meta.get("doi", ""),
            "OA状态": meta.get("oa_status", ""),
        })

    with out_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        fields = list(enriched[0].keys()) if enriched else []
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(enriched)

    statuses = sorted({r["下载状态"] for r in enriched})
    domains = sorted({r["领域"] for r in enriched if r["领域"]})
    tracks = sorted({r["轨道"] for r in enriched if r["轨道"]})
    counts: dict[str, int] = {}
    for row in enriched:
        counts[row["下载状态"]] = counts.get(row["下载状态"], 0) + 1
    summary = " · ".join(f"{h(status_note(k))}: {v}" for k, v in sorted(counts.items()))
    downloaded_count = counts.get("downloaded", 0) + counts.get("exists", 0)
    open_pdf_count = counts.get("open_pdf_available", 0)
    missing_count = counts.get("missing", 0)

    tr_html = []
    for row in enriched:
        local = row["本地PDF"]
        pdf = row["PDF直链"]
        landing = row["正确论文页"]
        top = " top" if "经典" in row["是否顶会顶刊"] or "Top" in row["是否顶会顶刊"] else ""
        tr_html.append(
            f'<tr class="{top.strip()}" data-status="{h(row["下载状态"])}" data-domain="{h(row["领域"])}" '
            f'data-track="{h(row["轨道"])}" data-score="{h(row["评分"])}" data-year="{h(row["年份"])}" '
            f'data-title="{h(row["标题"].lower())}">'
            f'<td>{h(row["序号"])}</td>'
            f'<td class="title">{h(row["标题"])}</td>'
            f'<td>{best_action(local, pdf, landing)}</td>'
            f'<td>{action_link("本地", local) if local else ""}</td>'
            f'<td>{action_link("PDF", pdf) if pdf else ""}</td>'
            f'<td>{action_link("论文页", landing)}</td>'
            f'<td><span class="status {h(row["下载状态"])}">{h(status_note(row["下载状态"]))}</span></td>'
            f'<td>{h(row["评分"])}</td>'
            f'<td>{h(row["年份"])}</td>'
            f'<td>{h(row["出处"])}</td>'
            f'<td>{h(row["领域"])}</td>'
            f'<td>{h(row["轨道"])}</td>'
            f'<td>{h(row["核心目标"])}</td>'
            f'<td class="abstract">{h(row["摘要"])}</td>'
            f'</tr>'
        )

    status_opts = "".join(f'<option value="{h(s)}">{h(status_note(s))}</option>' for s in statuses)
    domain_opts = "".join(f'<option value="{h(d)}">{h(d)}</option>' for d in domains)
    track_opts = "".join(f'<option value="{h(t)}">{h(t)}</option>' for t in tracks)

    html_doc = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>顶会顶刊论文总表</title>
<style>
:root {{ --ink:#1d2a2e; --muted:#6b7280; --paper:#fffaf0; --line:#e7dccc; --accent:#0c6b58; --warn:#a15c00; }}
body {{ margin:24px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; color:var(--ink); background:linear-gradient(135deg,#fff8e8,#edf7f3 55%,#f6efe2); }}
h1 {{ margin:0 0 6px; font-size:28px; }}
p {{ color:var(--muted); }}
.summary {{ display:flex; gap:10px; flex-wrap:wrap; margin:12px 0; }}
.card {{ background:white; border:1px solid var(--line); border-radius:14px; padding:10px 12px; box-shadow:0 8px 22px #0000000f; }}
.small {{ font-size:12px; color:var(--muted); }}
.controls {{ display:flex; flex-wrap:wrap; gap:10px; align-items:center; position:sticky; top:0; z-index:5; background:rgba(255,250,240,.95); backdrop-filter:blur(8px); border:1px solid var(--line); border-radius:16px; padding:12px; box-shadow:0 8px 24px #00000012; }}
select,input {{ padding:8px 10px; border:1px solid #cdbf9d; border-radius:10px; background:white; }}
.table-wrap {{ margin-top:14px; overflow:auto; border:1px solid var(--line); border-radius:18px; background:white; box-shadow:0 14px 36px #00000012; }}
table {{ min-width:1500px; width:100%; border-collapse:separate; border-spacing:0; background:white; }}
th,td {{ padding:9px 10px; border-bottom:1px solid #eee4d4; vertical-align:top; font-size:13px; }}
th {{ position:sticky; top:76px; z-index:4; background:#eadfc8; text-align:left; white-space:nowrap; }}
tr.top td:first-child::before {{ content:'★ '; color:#b7791f; }}
tr[data-status="downloaded"], tr[data-status="exists"] {{ background:#edf9ef; }}
tr[data-status="open_pdf_available"] {{ background:#fff7d6; }}
a {{ color:#0b5d7a; font-weight:700; text-decoration:none; }}
a.primary {{ display:inline-block; padding:6px 10px; border-radius:999px; background:var(--accent); color:white; }}
a.secondary {{ display:inline-block; padding:6px 10px; border-radius:999px; background:#f1eadb; color:#20433b; }}
.title {{ font-weight:750; max-width:360px; }}
.abstract {{ min-width:380px; max-width:560px; color:#374151; }}
.status {{ display:inline-block; padding:4px 8px; border-radius:999px; background:#eef2f7; white-space:nowrap; }}
.status.downloaded,.status.exists {{ background:#ccefd5; color:#14532d; }}
.status.open_pdf_available {{ background:#fde68a; color:#78350f; }}
.counter {{ margin-left:auto; font-weight:700; }}
</style>
</head>
<body>
<h1>顶会顶刊论文总表</h1>
<p>这个页面不做自动批量下载：扫描 <code>PHD-Buyya/</code> 后，已有本地 PDF 就打开本地文件；否则提供公开 PDF 链接或论文页，方便你手动处理。</p>
<div class="summary">
  <div class="card"><b>总论文</b><br>{len(enriched)}</div>
  <div class="card"><b>本地已有</b><br>{downloaded_count}</div>
  <div class="card"><b>有公开PDF链接</b><br>{open_pdf_count}</div>
  <div class="card"><b>仍未下载</b><br>{missing_count}</div>
  <div class="card"><b>状态统计</b><br><span class="small">{summary}</span></div>
</div>
<div class="controls">
<label>下载状态 <select id="status"><option value="">全部</option>{status_opts}</select></label>
<label>领域 <select id="domain"><option value="">全部</option>{domain_opts}</select></label>
<label>轨道 <select id="track"><option value="">全部</option>{track_opts}</select></label>
<label>排序 <select id="sort"><option value="score-desc">评分高到低</option><option value="status">下载状态</option><option value="year-desc">年份新到旧</option><option value="domain-score">领域→评分</option></select></label>
<label>搜索 <input id="q" placeholder="标题关键词"></label>
<span class="counter">显示 <span id="count">{len(enriched)}</span> / {len(enriched)}</span>
</div>
<div class="table-wrap"><table id="tbl">
<thead><tr><th>#</th><th>标题</th><th>一键入口</th><th>本地PDF</th><th>PDF链接</th><th>论文页</th><th>状态</th><th>评分</th><th>年份</th><th>出处</th><th>领域</th><th>轨道</th><th>目标</th><th>摘要</th></tr></thead>
<tbody>
{''.join(tr_html)}
</tbody>
</table></div>
<script>
const statusSel=document.getElementById('status'), domainSel=document.getElementById('domain'), trackSel=document.getElementById('track'), sortSel=document.getElementById('sort'), q=document.getElementById('q'), count=document.getElementById('count'), tbody=document.querySelector('#tbl tbody');
function apply() {{
  const sv=statusSel.value, dv=domainSel.value, tv=trackSel.value, qq=q.value.toLowerCase();
  let rows=[...tbody.querySelectorAll('tr')];
  rows.sort((a,b)=>{{
    const sa=Number(a.dataset.score||0), sb=Number(b.dataset.score||0), ya=Number(a.dataset.year||0), yb=Number(b.dataset.year||0);
    if(sortSel.value==='year-desc') return yb-ya || sb-sa;
    if(sortSel.value==='domain-score') return a.dataset.domain.localeCompare(b.dataset.domain,'zh') || sb-sa;
    if(sortSel.value==='status') return a.dataset.status.localeCompare(b.dataset.status) || sb-sa;
    return sb-sa || yb-ya;
  }});
  rows.forEach(r=>tbody.appendChild(r));
  let n=0;
  rows.forEach(tr=>{{
    const ok=(!sv||tr.dataset.status===sv)&&(!dv||tr.dataset.domain===dv)&&(!tv||tr.dataset.track===tv)&&(!qq||tr.dataset.title.includes(qq));
    tr.style.display=ok?'':'none'; if(ok)n++;
  }});
  count.textContent=n;
}}
[statusSel,domainSel,trackSel,sortSel,q].forEach(el=>el.addEventListener('input',apply));
apply();
</script>
</body>
</html>
"""
    out_html.write_text(html_doc, encoding="utf-8")
    print(f"Wrote {out_html}")
    print(f"Wrote {out_csv}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="papers_search_results.csv")
    parser.add_argument("--output", default="papers_search_results.html")
    parser.add_argument("--output-csv", default="papers_search_results_downloadable.csv")
    args = parser.parse_args(argv)
    build(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
