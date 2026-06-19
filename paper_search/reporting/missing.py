#!/usr/bin/env python3
"""Build an HTML list of papers that still need manual download."""
from __future__ import annotations

import argparse
import csv
import html
from collections import Counter
from pathlib import Path

from utils.paths import find_pdf_root
from pdf_ops.dedup import dedup_pdfs

DOWNLOADED_STATUSES = {"downloaded", "exists"}
STATUS_LABELS = {
    "missing": "本地未下载",
    "open_pdf_available": "有公开PDF链接",
    "downloaded": "已下载到本地",
    "exists": "本地已有PDF",
}

PDF_MIN_SIZE = 10_000


def h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def local_pdf_exists(row: dict[str, str], base: Path) -> bool:
    local_pdf = row.get("本地PDF", "")
    if not local_pdf:
        return False
    path = Path(local_pdf)
    if not path.is_absolute():
        path = base / path
    try:
        return path.exists() and path.stat().st_size > PDF_MIN_SIZE
    except OSError:
        return False


def refresh_with_local_scan(rows: list[dict[str, str]], base: Path) -> dict[str, int]:
    """Scan PHD-Buyya only before deciding what is still missing."""
    try:
        from utils.reconcile import best_match, index_local_pdfs, rel_to_report, should_replace_local_pdf
    except Exception as exc:
        print(f"[local-scan] skipped: {exc}")
        return {"indexed": 0, "matched": 0}

    repo = base.parent
    buyya_dir = find_pdf_root(repo)
    local_pdfs = index_local_pdfs([
        (buyya_dir, "PHD-Buyya"),
    ])
    matched_rows: set[int] = set()
    for pdf in local_pdfs:
        idx, _score, _method = best_match(pdf, rows)
        if idx is None:
            continue
        matched_rows.add(idx)
        row = rows[idx - 1]
        if not should_replace_local_pdf(row, pdf.path, base, buyya_dir):
            continue
        row["本地PDF"] = rel_to_report(pdf.path, base)
        row["下载状态"] = "exists"
        row["下载说明"] = f"本地已有PDF({pdf.source})"
    matched = len(matched_rows)
    print(f"[local-scan] folder={buyya_dir} indexed={len(local_pdfs)} matched_rows={matched}")
    return {"indexed": len(local_pdfs), "matched": matched, "folder": str(buyya_dir)}


def is_missing(row: dict[str, str], base: Path) -> bool:
    status = row.get("下载状态", "")
    return not (status in DOWNLOADED_STATUSES and local_pdf_exists(row, base))


def need_type(row: dict[str, str]) -> str:
    if row.get("PDF直链"):
        return "有公开PDF链接"
    # Accept multiple possible column names for the landing-page link.
    has_landing = (
        row.get("正确论文页", "")
        or row.get("论文页", "")
        or row.get("原始链接", "")
        or row.get("DOI", "")
    )
    if has_landing:
        return "手动打开论文页"
    return "需要人工确认"


def link(label: str, url: str, css: str = "") -> str:
    if not url:
        return ""
    cls = f' class="{h(css)}"' if css else ""
    return f'<a{cls} href="{h(url)}" target="_blank" rel="noopener">{h(label)}</a>'


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="papers_search_results_downloadable.csv")
    parser.add_argument("--output", default="papers_missing_downloads.html")
    parser.add_argument("--output-csv", default="papers_missing_downloads.csv")
    parser.add_argument("--no-scan-local", dest="scan_local", action="store_false", help="do not rescan local PDF folders before building the missing list")
    parser.add_argument("--dedup", action="store_true", help="remove exact-duplicate PDFs from PHD-Buyya/ before building the list")
    parser.add_argument("--dry-run-dedup", action="store_true", help="simulate PDF deduplication without deleting any files")
    parser.set_defaults(scan_local=True)
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parents[1]
    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = base / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = base / output_path
    output_csv = Path(args.output_csv)
    if not output_csv.is_absolute():
        output_csv = base / output_csv

    all_rows = load_rows(input_path)
    scan_stats: dict[str, object] = {"indexed": 0, "matched": 0, "folder": ""}
    if args.scan_local:
        scan_stats = refresh_with_local_scan(all_rows, base)
        write_rows(input_path, all_rows)

    # PDF 重复检测与去重（在判断"缺哪篇"之前清理，避免重复占位影响判定）
    if args.dedup or args.dry_run_dedup:
        dry = args.dry_run_dedup and not args.dedup
        pdf_root = find_pdf_root(repo=base.parent)
        stats = dedup_pdfs(pdf_root, dry_run=dry)
        print(f"[dedup] {'dry-run' if dry else 'done'}")
        print(f"  重复组: {stats['dup_groups']} 组，"
              f"副本: {stats['to_delete']} 个")
        print(f"  删除: {stats['deleted']}，失败: {stats['fail']}")
        print(f"  PHD-Buyya 剩余: {stats['total_after']} 个 PDF")

    rows = [r for r in all_rows if is_missing(r, base)]
    for r in rows:
        r["人工处理类型"] = need_type(r)

    fields = list(rows[0].keys()) if rows else (list(all_rows[0].keys()) + ["人工处理类型"] if all_rows else [])
    with output_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        if fields:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    by_status = Counter(r.get("下载状态", "") for r in rows)
    by_type = Counter(r.get("人工处理类型", "") for r in rows)
    by_domain = Counter(r.get("领域", "") for r in rows)
    statuses = sorted(by_status)
    types = sorted(by_type)
    domains = sorted(d for d in by_domain if d)
    tracks = sorted({r.get("轨道", "") for r in rows if r.get("轨道", "")})

    status_opts = "".join(f'<option value="{h(s)}">{h(STATUS_LABELS.get(s, s))} ({by_status[s]})</option>' for s in statuses)
    type_opts = "".join(f'<option value="{h(t)}">{h(t)} ({by_type[t]})</option>' for t in types)
    domain_opts = "".join(f'<option value="{h(d)}">{h(d)} ({by_domain[d]})</option>' for d in domains)
    track_opts = "".join(f'<option value="{h(t)}">{h(t)}</option>' for t in tracks)
    status_summary = " · ".join(f"{STATUS_LABELS.get(k, k)}: {v}" for k, v in by_status.most_common())
    type_summary = " · ".join(f"{k}: {v}" for k, v in by_type.most_common())

    body_rows = []
    for r in rows:
        status = r.get("下载状态", "")
        title = r.get("标题", "")
        # Accept multiple possible column names for the landing-page link.
        correct_url = (
            r.get("正确论文页", "")
            or r.get("论文页", "")
            or r.get("原始链接", "")
            or ""
        )
        original_url = r.get("原始链接", "")
        pdf_url = r.get("PDF直链", "")
        doi = r.get("DOI", "")
        doi_url = f"https://doi.org/{doi}" if doi and not doi.startswith("http") else doi
        best = pdf_url or correct_url or original_url or doi_url
        body_rows.append(
            f'<tr data-status="{h(status)}" data-type="{h(r.get("人工处理类型", ""))}" '
            f'data-domain="{h(r.get("领域", ""))}" data-track="{h(r.get("轨道", ""))}" '
            f'data-score="{h(r.get("评分", "0"))}" data-year="{h(r.get("年份", "0"))}" data-title="{h(title.lower())}">'
            f'<td>{h(r.get("序号", ""))}</td>'
            f'<td class="title">{h(title)}</td>'
            f'<td>{link("打开下载页", best, "primary")}</td>'
            f'<td>{link("正确论文页", correct_url)}</td>'
            f'<td>{link("PDF链接", pdf_url)}</td>'
            f'<td>{link("DOI", doi_url)}</td>'
            f'<td><span class="need">{h(r.get("人工处理类型", ""))}</span></td>'
            f'<td><span class="status {h(status)}">{h(STATUS_LABELS.get(status, status))}</span></td>'
            f'<td>{h(r.get("评分", ""))}</td>'
            f'<td>{h(r.get("年份", ""))}</td>'
            f'<td>{h(r.get("出处", ""))}</td>'
            f'<td>{h(r.get("领域", ""))}</td>'
            f'<td>{h(r.get("轨道", ""))}</td>'
            f'<td class="abstract">{h(r.get("摘要", ""))}</td>'
            '</tr>'
        )

    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>未下载论文清单</title>
<style>
:root {{ --ink:#20302f; --muted:#667085; --line:#dfd5c3; --bg:#fbf4e8; --accent:#0f766e; }}
body {{ margin:24px; color:var(--ink); background:linear-gradient(135deg,#fff7e6,#eaf6f2 60%,#f8ede1); font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; }}
h1 {{ margin:0 0 8px; font-size:30px; }}
p {{ color:var(--muted); line-height:1.55; }}
.summary {{ display:flex; gap:10px; flex-wrap:wrap; margin:12px 0; }}
.card {{ background:white; border:1px solid var(--line); border-radius:14px; padding:10px 12px; box-shadow:0 8px 22px #0000000f; }}
.controls {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; position:sticky; top:0; z-index:5; background:rgba(251,244,232,.94); backdrop-filter:blur(8px); border:1px solid var(--line); border-radius:16px; padding:12px; }}
select,input {{ padding:8px 10px; border:1px solid #c7b99c; border-radius:10px; background:white; }}
.table-wrap {{ margin-top:14px; overflow:auto; border:1px solid var(--line); border-radius:18px; background:white; box-shadow:0 12px 32px #00000012; }}
table {{ min-width:1500px; width:100%; border-collapse:separate; border-spacing:0; background:white; }}
th,td {{ padding:9px 10px; border-bottom:1px solid #eee3d2; vertical-align:top; font-size:13px; }}
th {{ position:sticky; top:76px; z-index:4; background:#eadfca; text-align:left; white-space:nowrap; }}
tr[data-type="有公开PDF链接"] {{ background:#edf9ef; }}
tr[data-type="手动打开论文页"] {{ background:#fff8e1; }}
a {{ color:#0b5d7a; font-weight:700; text-decoration:none; }}
a.primary {{ display:inline-block; padding:6px 10px; border-radius:999px; background:var(--accent); color:white; white-space:nowrap; }}
.title {{ min-width:300px; max-width:420px; font-weight:750; }}
.abstract {{ min-width:360px; max-width:520px; color:#374151; }}
.status,.need {{ display:inline-block; padding:4px 8px; border-radius:999px; background:#eef2f7; white-space:nowrap; }}
.need {{ background:#ede9fe; color:#4c1d95; }}
.status.open_pdf_available {{ background:#fde68a; color:#78350f; }}
.status.missing {{ background:#e0f2fe; color:#075985; }}
.counter {{ margin-left:auto; font-weight:800; }}
.small {{ font-size:12px; color:var(--muted); }}
</style>
</head>
<body>
<h1>未下载论文清单</h1>
<p>这个页面只列出 <code>PHD-Buyya/</code> 里还没有匹配到 PDF 的论文。下载完直接放进 <code>PHD-Buyya/</code>，再重新生成报告即可。</p>
<div class="summary">
  <div class="card"><b>总论文</b><br>{len(all_rows)}</div>
  <div class="card"><b>未下载</b><br>{len(rows)}</div>
  <div class="card"><b>已下载</b><br>{len(all_rows) - len(rows)}</div>
  <div class="card"><b>扫描文件夹</b><br><span class="small">{h(scan_stats.get("folder", ""))}</span></div>
  <div class="card"><b>本地PDF匹配</b><br>{h(scan_stats.get("matched", 0))} / {h(scan_stats.get("indexed", 0))}</div>
  <div class="card"><b>按状态</b><br><span class="small">{h(status_summary)}</span></div>
  <div class="card"><b>人工处理类型</b><br><span class="small">{h(type_summary)}</span></div>
</div>
<div class="controls">
<label>处理类型 <select id="type"><option value="">全部</option>{type_opts}</select></label>
<label>下载状态 <select id="status"><option value="">全部</option>{status_opts}</select></label>
<label>领域 <select id="domain"><option value="">全部</option>{domain_opts}</select></label>
<label>轨道 <select id="track"><option value="">全部</option>{track_opts}</select></label>
<label>排序 <select id="sort"><option value="score-desc">评分高到低</option><option value="type-score">处理类型→评分</option><option value="year-desc">年份新到旧</option><option value="domain-score">领域→评分</option></select></label>
<label>搜索 <input id="q" placeholder="标题关键词"></label>
<span class="counter">显示 <span id="count">{len(rows)}</span> / {len(rows)}</span>
</div>
<div class="table-wrap"><table id="tbl">
<thead><tr><th>#</th><th>标题</th><th>打开下载页</th><th>正确论文页</th><th>PDF链接</th><th>DOI</th><th>处理类型</th><th>下载状态</th><th>评分</th><th>年份</th><th>出处</th><th>领域</th><th>轨道</th><th>摘要</th></tr></thead>
<tbody>
{''.join(body_rows)}
</tbody>
</table></div>
<script>
const typeSel=document.getElementById('type'), statusSel=document.getElementById('status'), domainSel=document.getElementById('domain'), trackSel=document.getElementById('track'), sortSel=document.getElementById('sort'), q=document.getElementById('q'), count=document.getElementById('count'), tbody=document.querySelector('#tbl tbody');
function apply() {{
  const tv=typeSel.value, sv=statusSel.value, dv=domainSel.value, rv=trackSel.value, qq=q.value.toLowerCase();
  let rows=[...tbody.querySelectorAll('tr')];
  rows.sort((a,b)=>{{
    const sa=Number(a.dataset.score||0), sb=Number(b.dataset.score||0), ya=Number(a.dataset.year||0), yb=Number(b.dataset.year||0);
    if(sortSel.value==='year-desc') return yb-ya || sb-sa;
    if(sortSel.value==='domain-score') return a.dataset.domain.localeCompare(b.dataset.domain,'zh') || sb-sa;
    if(sortSel.value==='type-score') return a.dataset.type.localeCompare(b.dataset.type,'zh') || sb-sa;
    return sb-sa || yb-ya;
  }});
  rows.forEach(r=>tbody.appendChild(r));
  let n=0;
  rows.forEach(tr=>{{
    const ok=(!tv||tr.dataset.type===tv)&&(!sv||tr.dataset.status===sv)&&(!dv||tr.dataset.domain===dv)&&(!rv||tr.dataset.track===rv)&&(!qq||tr.dataset.title.includes(qq));
    tr.style.display=ok?'':'none'; if(ok)n++;
  }});
  count.textContent=n;
}}
[typeSel,statusSel,domainSel,trackSel,sortSel,q].forEach(el=>el.addEventListener('input',apply));
apply();
</script>
</body>
</html>
"""
    output_path.write_text(content, encoding="utf-8")
    print(f"Wrote {output_path}")
    print(f"Wrote {output_csv}")
    print(f"Missing {len(rows)} / {len(all_rows)}")
    print("Status:", dict(by_status))
    print("Type:", dict(by_type))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
