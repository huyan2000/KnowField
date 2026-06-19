#!/usr/bin/env python3
"""Reconcile local PDF folders with the paper-search reports.

This script indexes local PDF titles from PHD-Buyya, links matched PDFs back to
the downloadable CSV, and reports local PDFs that the crawler/report did not cover.
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from difflib import SequenceMatcher

from utils.paths import find_pdf_root

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None

# ── Constants ──────────────────────────────────────────────────
# Minimum file size (bytes) for a PDF to be considered a real download.
# Files smaller than this are treated as stub/placeholder files.
PDF_MIN_SIZE = 10_000

# Minimum normalized similarity score (0–1) required to consider a local
# PDF title a match against a report row title.  Values below this threshold
# are reported as "uncovered".
PDF_TITLE_MATCH_THRESHOLD = 0.82

# Header / boilerplate lines to skip when extracting the title from page 1
# of a PDF (pypdf text extraction).
STOP_LINES = {
    "abstract", "introduction", "arxiv", "ieee transactions", "ieee internet of things journal",
    "ieee transactions on mobile computing", "received", "accepted", "published online",
}

# Overrides for PDFs whose first-page text is too noisy for title extraction.
KNOWN_TITLE_OVERRIDES: dict[str, str] = {
    "1-s2.0-S0950705125006069-main.pdf": "Adaptive aggregation for federated learning using representation ability based on feature alignment",
    "A_Heterogeneity-Aware_Adaptive_Federated_Learning_Framework_for_Short-Term_Forecasting_in_Electric_IoT_Systems.pdf": "A Heterogeneity-Aware Adaptive Federated Learning Framework for Short-Term Forecasting in Electric IoT Systems",
    "Federated_Learning_With_Client_Clustering_Selection_and_Quality-Aware_Model_Aggregation_2024.pdf": "Federated Learning With Client Clustering Selection and Quality-Aware Model Aggregation",
    "GossipFL_A_Decentralized_Federated_Learning_Framework_With_Sparsified_and_Adaptive_Communication.pdf": "GossipFL: A Decentralized Federated Learning Framework With Sparsified and Adaptive Communication",
}


@dataclass
class LocalPdf:
    path: Path
    source: str
    title: str
    norm: str
    matched_index: int | None = None
    matched_title: str = ""
    match_score: float = 0.0
    match_method: str = ""
    content_checked: bool = False   # True = pypdf successfully extracted text from this PDF


def h(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (text or "").lower())


def clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line or "").strip()
    line = line.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return line


def extract_text(path: Path, pages: int = 1) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
        text = []
        for page in reader.pages[:pages]:
            text.append(page.extract_text() or "")
        return "\n".join(text)
    except Exception:
        return ""


def title_from_filename(path: Path) -> str:
    name = path.stem
    name = re.sub(r"^\d+_\d{4}_\d+_", "", name)
    name = re.sub(r"_[0-9a-f]{8}$", "", name)
    name = re.sub(r"^\d{8}_\d{4}\.\d+v?\d*_", "", name)
    name = re.sub(r"^\d{4}\.\d+v?\d*$", "", name)
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    return name


def extract_title(path: Path) -> tuple[str, bool]:
    """返回 (title, content_checked)。content_checked=True 表示 pypdf 确实提取到了文本。"""
    if path.name in KNOWN_TITLE_OVERRIDES:
        return KNOWN_TITLE_OVERRIDES[path.name], False   # override，不算真正提取
    text = extract_text(path, pages=1)
    checked = bool(text and text.strip())
    lines = [clean_line(x) for x in text.splitlines()]
    lines = [x for x in lines if x]
    if not lines:
        return title_from_filename(path), checked

    # Drop obvious headers.
    filtered = []
    for line in lines[:40]:
        low = line.lower()
        if any(low.startswith(s) for s in STOP_LINES):
            continue
        if re.search(r"^(\d+|[a-z]?\s*\d+)$", low):
            continue
        if "copyright" in low or "doi:" in low or "arxiv:" in low:
            continue
        filtered.append(line)

    if not filtered:
        return title_from_filename(path), checked

    title_lines = []
    for line in filtered[:12]:
        low = line.lower()
        if low.startswith("abstract") or "@" in line:
            break
        if re.match(r"^[A-Z][a-z]+\s+[A-Z]", line) and title_lines:
            # Looks like author names after title.
            break
        if len(line) < 4:
            continue
        title_lines.append(line)
        joined = " ".join(title_lines)
        if len(joined) > 160:
            break
        if len(title_lines) >= 5:
            break
    title = clean_line(" ".join(title_lines))
    title = re.sub(r"\s+", " ", title).strip(" -")
    if len(title) < 12:
        return title_from_filename(path), checked
    return title, checked


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def best_match(local: LocalPdf, rows: list[dict[str, str]]) -> tuple[int | None, float, str]:
    ln = local.norm
    lc = compact(local.title)
    best_idx = None
    best_score = 0.0
    method = ""
    for idx, row in enumerate(rows, start=1):
        title = row.get("标题", "")
        rn = normalize(title)
        rc = compact(title)
        if not rn:
            continue
        score = SequenceMatcher(None, ln, rn).ratio()
        if lc and rc and (lc in rc or rc in lc):
            score = max(score, 0.98 if min(len(lc), len(rc)) >= 32 else 0.90)
        # Also try filename stem because some extracted titles include headers.
        fn = normalize(title_from_filename(local.path))
        if fn:
            score = max(score, SequenceMatcher(None, fn, rn).ratio() * 0.95)
        if score > best_score:
            best_idx = idx
            best_score = score
            method = "title/fuzzy"
    if best_score >= PDF_TITLE_MATCH_THRESHOLD:
        return best_idx, best_score, method
    return None, best_score, "no_match"


def index_local_pdfs(paths: list[tuple[Path, str]]) -> list[LocalPdf]:
    out: list[LocalPdf] = []
    seen: set[Path] = set()
    for folder, source in paths:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*.pdf")):
            rp = path.resolve()
            if rp in seen:
                continue
            seen.add(rp)
            title, checked = extract_title(path)
            out.append(LocalPdf(path=path, source=source, title=title, norm=normalize(title), content_checked=checked))
    return out


def pdf_priority(path: Path, root: Path) -> tuple[int, str]:
    try:
        rel = path.resolve().relative_to(root.resolve())
        depth = len(rel.parts)
    except Exception:
        depth = 999
    return (depth, str(path))


def local_pdf_exists(path_value: str, base: Path) -> bool:
    if not path_value:
        return False
    path = Path(path_value)
    if not path.is_absolute():
        path = base / path
    try:
        return path.exists() and path.stat().st_size > PDF_MIN_SIZE
    except OSError:
        return False


def should_replace_local_pdf(row: dict[str, str], candidate: Path, base: Path, root: Path) -> bool:
    existing = row.get("本地PDF", "")
    if not local_pdf_exists(existing, base):
        return True
    existing_path = Path(existing)
    if not existing_path.is_absolute():
        existing_path = base / existing_path
    return pdf_priority(candidate, root) < pdf_priority(existing_path, root)


def rel_to_report(path: Path, report_dir: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), report_dir.resolve())
    except Exception:
        return str(path)


def copy_unmatched(unmatched: list[LocalPdf], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for pdf in unmatched:
        dest = out_dir / pdf.path.name
        if not dest.exists() or dest.stat().st_size != pdf.path.stat().st_size:
            shutil.copy2(pdf.path, dest)


def build_html(rows: list[LocalPdf], out_path: Path, report_dir: Path) -> None:
    source_opts = sorted({x.source for x in rows})
    source_options = "".join(f'<option value="{h(s)}">{h(s)}</option>' for s in source_opts)
    body = []
    for pdf in rows:
        link = rel_to_report(pdf.path, out_path.parent)
        body.append(
            f'<tr data-source="{h(pdf.source)}" data-score="{pdf.match_score:.4f}" data-title="{h(pdf.title.lower())}">'
            f'<td>{h(pdf.source)}</td>'
            f'<td class="title">{h(pdf.title)}</td>'
            f'<td>{h(pdf.path.name)}</td>'
            f'<td><a class="primary" href="{h(link)}" target="_blank">打开PDF</a></td>'
            f'<td>{h(pdf.matched_index or "")}</td>'
            f'<td>{h(pdf.matched_title)}</td>'
            f'<td>{pdf.match_score:.3f}</td>'
            f'</tr>'
        )
    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>本地PDF与爬虫结果补全报告</title>
<style>
body {{ margin:24px; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif; background:#f7f3e8; color:#1f2933; }}
h1 {{ margin:0 0 8px; }}
.controls {{ display:flex; gap:10px; flex-wrap:wrap; align-items:center; position:sticky; top:0; background:#f7f3e8; border:1px solid #dccfb8; border-radius:14px; padding:12px; }}
select,input {{ padding:8px 10px; border:1px solid #c7b99c; border-radius:10px; background:white; }}
table {{ width:100%; border-collapse:separate; border-spacing:0; margin-top:14px; background:white; border:1px solid #e4d8c5; border-radius:16px; overflow:hidden; }}
th,td {{ padding:9px 10px; border-bottom:1px solid #eee3d2; vertical-align:top; font-size:13px; }}
th {{ position:sticky; top:72px; background:#eadfca; text-align:left; }}
.title {{ font-weight:750; max-width:460px; }}
a {{ color:#0b5d7a; font-weight:700; text-decoration:none; }}
a.primary {{ display:inline-block; padding:6px 10px; border-radius:999px; background:#0f766e; color:white; }}
.counter {{ margin-left:auto; font-weight:800; }}
</style>
</head>
<body>
<h1>本地PDF与爬虫结果补全报告</h1>
<p>这里列出本地 PDF 的标题提取结果、是否匹配当前 paper_search CSV，以及未覆盖论文。匹配分数低于 {PDF_TITLE_MATCH_THRESHOLD} 视为未覆盖。</p>
<div class="controls">
<label>来源 <select id="source"><option value="">全部</option>{source_options}</select></label>
<label>搜索 <input id="q" placeholder="标题关键词"></label>
<label>显示 <select id="mode"><option value="">全部</option><option value="matched">已匹配</option><option value="unmatched">未覆盖</option></select></label>
<span class="counter">显示 <span id="count">{len(rows)}</span> / {len(rows)}</span>
</div>
<table id="tbl">
<thead><tr><th>来源</th><th>提取标题</th><th>文件名</th><th>PDF</th><th>匹配序号</th><th>匹配标题</th><th>分数</th></tr></thead>
<tbody>{''.join(body)}</tbody>
</table>
<script>
const source=document.getElementById('source'), q=document.getElementById('q'), mode=document.getElementById('mode'), count=document.getElementById('count');
function apply() {{
 const sv=source.value, qq=q.value.toLowerCase(), mv=mode.value; let n=0;
 document.querySelectorAll('#tbl tbody tr').forEach(tr=>{{
   const matched=Number(tr.dataset.score||0)>={PDF_TITLE_MATCH_THRESHOLD};
   const ok=(!sv||tr.dataset.source===sv)&&(!qq||tr.dataset.title.includes(qq))&&(!mv||(mv==='matched'?matched:!matched));
   tr.style.display=ok?'':'none'; if(ok)n++;
 }});
 count.textContent=n;
}}
[source,q,mode].forEach(el=>el.addEventListener('input',apply)); apply();
</script>
</body>
</html>
"""
    out_path.write_text(content, encoding="utf-8")


def build_unmatched_html(rows: list[dict[str, str]], out_path: Path) -> None:
    body = []
    for row in rows:
        body.append(
            f'<tr data-title="{h(row.get("提取标题", "").lower())}">'
            f'<td>{h(row.get("提取标题", ""))}</td>'
            f'<td>{h(row.get("文件名", ""))}</td>'
            f'<td><a href="{h(row.get("PDF路径", ""))}" target="_blank">打开PDF</a></td>'
            f'<td>{h(row.get("最佳匹配分数", ""))}</td>'
            f'<td>{h(row.get("建议", ""))}</td>'
            '</tr>'
        )
    content = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>本地已有但爬虫未覆盖论文</title>
<style>
body{{margin:24px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#fbf6ea;color:#1f2933}}
table{{width:100%;border-collapse:collapse;background:white;border:1px solid #e4d8c5}}
th,td{{padding:10px;border-bottom:1px solid #eee3d2;vertical-align:top;text-align:left}}
th{{background:#eadfca}}
a{{color:#0b5d7a;font-weight:700;text-decoration:none}}
input{{padding:8px 10px;border:1px solid #c7b99c;border-radius:10px;margin:10px 0 14px;width:min(520px,90vw)}}
</style>
</head>
<body>
<h1>本地已有但爬虫未覆盖论文</h1>
<p>这些 PDF 来自 PHD-Buyya，但没有匹配到当前 paper_search 主列表。建议人工判断是否加入爬虫 seed/query。</p>
<input id="q" placeholder="搜索标题">
<table id="tbl"><thead><tr><th>标题</th><th>文件名</th><th>PDF</th><th>最佳匹配分数</th><th>建议</th></tr></thead><tbody>{''.join(body)}</tbody></table>
<script>
const q=document.getElementById('q');q.addEventListener('input',()=>{{const v=q.value.toLowerCase();document.querySelectorAll('#tbl tbody tr').forEach(tr=>tr.style.display=(!v||tr.dataset.title.includes(v))?'':'none')}});
</script>
</body></html>
"""
    out_path.write_text(content, encoding="utf-8")


def reconcile_local_pdfs(write_reports: bool = True, *, enable_multipaper: bool = True) -> dict[str, int]:
    # utils/reconcile.py → paper_search/ 上一级
    paper_search = Path(__file__).resolve().parent.parent
    repo = paper_search.parent
    rows_path = paper_search / "papers_search_results_downloadable.csv"
    if not rows_path.exists():
        rows_path = paper_search / "papers_search_results.csv"
    rows = load_rows(rows_path)

    buyya_dir = find_pdf_root(repo)
    local_pdfs = index_local_pdfs([
        (buyya_dir, "PHD-Buyya"),
    ])

    for pdf in local_pdfs:
        idx, score, method = best_match(pdf, rows)
        pdf.matched_index = idx
        pdf.match_score = score
        pdf.match_method = method
        if idx is not None:
            pdf.matched_title = rows[idx - 1].get("标题", "")

    matched_buyya = [p for p in local_pdfs if p.source == "PHD-Buyya" and p.matched_index is not None]
    unmatched_buyya = [p for p in local_pdfs if p.source == "PHD-Buyya" and p.matched_index is None]
    matched_all = [p for p in local_pdfs if p.matched_index is not None]
    matched_row_count = len({p.matched_index for p in matched_all if p.matched_index is not None})
    matched_buyya_row_count = len({p.matched_index for p in matched_buyya if p.matched_index is not None})

    # Update downloadable rows with any matched local PDF. This makes the
    # missing-download report reflect files manually added after the downloader ran.
    # Also write back the content_checked flag so the final report knows which PDFs
    # have had their text successfully extracted by pypdf.
    for pdf in matched_all:
        row = rows[pdf.matched_index - 1]
        if not should_replace_local_pdf(row, pdf.path, paper_search, buyya_dir):
            continue
        row["本地PDF"] = rel_to_report(pdf.path, paper_search)
        row["下载状态"] = "exists"
        row["下载说明"] = f"本地已有PDF({pdf.source})"
        row["内容已检测"] = "是" if pdf.content_checked else "否"

    # ── Multi-paper PDF reverse-match ──────────────────────────────────────
    # 一份 PDF 可能涵盖报告里的多篇论文（合订本 / 多篇论文打包）。
    # 用 PDF outline + 章节首页扫描，把同一份 PDF 也回填到报告里"未下载"的
    # 同书章节论文行上。
    multipaper_extra_rows = 0
    multipaper_pdfs = 0
    if enable_multipaper:
        try:
            from utils.multipaper import find_multipaper_pdfs
        except Exception:
            find_multipaper_pdfs = None  # type: ignore[assignment]
        if find_multipaper_pdfs is not None:
            already_indexed = {pdf.matched_index - 1 for pdf in matched_all if pdf.matched_index is not None}
            pdf_paths = [p.path for p in local_pdfs]
            multi_results = find_multipaper_pdfs(pdf_paths, rows)
            for m in multi_results:
                contributed = 0
                for row_idx in m.matched_rows:
                    if row_idx in already_indexed:
                        continue
                    row = rows[row_idx]
                    # 已有独立 PDF 不要覆盖
                    existing_local = (row.get("本地PDF") or "").strip()
                    if existing_local:
                        existing_path = Path(existing_local)
                        if not existing_path.is_absolute():
                            existing_path = paper_search / existing_path
                        if existing_path.exists():
                            continue
                    row["本地PDF"] = rel_to_report(m.pdf_path, paper_search)
                    row["下载状态"] = "exists"
                    row["下载说明"] = f"本地已有PDF（合订本：{m.pdf_path.name}）"
                    row["内容已检测"] = row.get("内容已检测") or "是"
                    already_indexed.add(row_idx)
                    contributed += 1
                if contributed:
                    multipaper_extra_rows += contributed
                    multipaper_pdfs += 1

    write_rows(paper_search / "papers_search_results_downloadable.csv", rows)

    out_rows = []
    for pdf in unmatched_buyya:
        out_rows.append({
            "来源": pdf.source,
            "文件名": pdf.path.name,
            "提取标题": pdf.title,
            "PDF路径": rel_to_report(pdf.path, paper_search),
            "内容已检测": "是" if pdf.content_checked else "否",
            "最佳匹配分数": f"{pdf.match_score:.3f}",
            "最佳匹配标题": pdf.matched_title,
            "建议": "建议加入爬虫seed/query或作为本地补充论文人工判断",
        })
    if write_reports:
        report_rows = [p for p in local_pdfs if p.source == "PHD-Buyya"]
        build_html(report_rows, paper_search / "local_pdf_reconciliation.html", paper_search)
        if out_rows:
            write_rows(paper_search / "local_pdfs_not_in_search.csv", out_rows)
        else:
            (paper_search / "local_pdfs_not_in_search.csv").write_text("来源,文件名,提取标题,PDF路径,最佳匹配分数,最佳匹配标题,建议\n", encoding="utf-8-sig")
        build_unmatched_html(out_rows, paper_search / "local_pdfs_not_in_search.html")
        copy_unmatched(unmatched_buyya, paper_search / "local_pdfs_not_in_search")

    print(f"Local PDF folder: {buyya_dir}")
    print(f"Local PDFs indexed: {len(local_pdfs)}")
    print(f"Local PDFs matched to search rows: {matched_row_count} rows / {len(matched_all)} PDFs")
    print(f"PHD-Buyya matched: {matched_buyya_row_count} rows / {len(matched_buyya)} PDFs")
    print(f"PHD-Buyya PDFs not in current main list: {len(unmatched_buyya)}")
    if enable_multipaper and multipaper_extra_rows:
        print(f"Multi-paper bundles: {multipaper_pdfs} PDFs covered {multipaper_extra_rows} extra rows")
    if write_reports:
        print("Wrote local_pdf_reconciliation.html")
        print("Wrote local_pdfs_not_in_search.csv")
    return {
        "local_indexed": len(local_pdfs),
        "local_matched": matched_row_count,
        "buyya_matched": matched_buyya_row_count,
        "buyya_uncovered": len(unmatched_buyya),
        "multipaper_pdfs": multipaper_pdfs,
        "multipaper_rows": multipaper_extra_rows,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default=None)
    parser.add_argument("--write-reports", action="store_true", help="also write local reconciliation HTML/CSV helper reports")
    args = parser.parse_args(argv)
    reconcile_local_pdfs(write_reports=args.write_reports)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
