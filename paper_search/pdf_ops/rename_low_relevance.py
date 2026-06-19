#!/usr/bin/env python3
"""
对 arxiv_low_relevance/ 中 15 篇 PDF 做报告标题重命名：
原始文件都能从文件名看出标题关键字，
直接比对报告标题列，四分位数降低到 0.60 + 文件名 vs 报告标题截段加强力度，
并用一遍文件名逐词 vs 报告标题密钥的精确匹配（substring）优先。
"""
import csv, re, shutil
from pathlib import Path
from difflib import SequenceMatcher

def normalize(s):
    return re.sub(r"[^a-z0-9]+"," ", (s or "").lower()).strip()
def compact(s):
    return re.sub(r"[^a-z0-9]+","", (s or "").lower())
def score(a, b):
    an, bn = normalize(a), normalize(b)
    if not an or not bn: return 0.0
    s = SequenceMatcher(None, an, bn).ratio()
    ac, bc = compact(a), compact(b)
    if ac and bc and (ac in bc or bc in ac):
        s = max(s, 0.98 if min(len(ac), len(bc)) >= 32 else 0.90)
    return s

base     = Path(__file__).resolve().parents[1]
repo     = base.parent
from utils.paths import find_pdf_root
pdf_root = find_pdf_root(repo)
low_dir  = pdf_root / "arxiv_low_relevance"

report_rows = list(csv.DictReader((base / "paper_search_report.csv").open(encoding="utf-8-sig")))
report_titles = [r["标题"] for r in report_rows]

pdfs = sorted(low_dir.glob("*.pdf"))
print(f"扫描 arxiv_low_relevance/: {len(pdfs)} PDFs\n")

THRESH = 0.60   # 文件名匹配下降后的宽松阈值

matched, unmatched = 0, 0
for pdf in pdfs:
    # 从文件名提取原始论文标题字串（去掉日期/ID前缀）
    raw = pdf.stem
    # 去掉 arxiv_id 日期前缀 "20260120_2601.13824_"
    clean_name = re.sub(r"^\d{8}_\d{4}\.\d+v?\d+_", "", raw)
    clean_name = clean_name.replace("_", " ").replace("-", " ")
    clean_name = re.sub(r"\s+", " ", clean_name).strip()

    # 也在 PDF 前5页尝试提取 span
    try:
        from pypdf import PdfReader
        r = PdfReader(str(pdf))
        fulltxt = "\n".join(p.extract_text() or "" for p in r.pages[:5])
    except Exception:
        fulltxt = ""
    lines = [l.strip() for l in fulltxt.splitlines() if l.strip() and len(l.strip()) >= 15]
    STOP = {"abstract","introduction","arxiv","received","accepted","published online"}
    good = [l for l in lines if not any(l.lower().startswith(s) for s in STOP) and "copyright" not in l.lower()]
    # span
    span = ""
    for i, ln in enumerate(good[:10]):
        s = ln
        for j in range(i+1, min(i+3, len(good))):
            nxt = good[j]
            if nxt is not ln: s += " " + nxt
        if 15 <= len(s) <= 200:
            span = s
            break
    if not span:
        span = clean_name

    # 三路全局扫描
    best_s, best_i, best_m = 0.0, -1, ""
    for ri, row in enumerate(report_rows):
        rtitle = row["标题"]
        # filename vs title
        s = score(clean_name, rtitle)
        if s > best_s: best_s, best_i, best_m = s, ri, "fname→title"
        # span vs title
        s2 = score(span, rtitle)
        if s2 > best_s: best_s, best_i, best_m = s2, ri, "span→title"
        # filename vs title_compact
        ec, rc = compact(clean_name), compact(rtitle)
        if ec and rc and (ec in rc or rc in ec):
            bonus = 0.98 if min(len(ec),len(rc))>=32 else 0.90
            if bonus > best_s: best_s, best_i, best_m = bonus, ri, "compact_in"

    if best_s >= THRESH:
        std = report_rows[best_i]["标题"]
        new_name = re.sub(r"[^A-Za-z0-9]+","_", std.lower()).strip("_")[:80] + ".pdf"
        print(f"  ✓ {best_s:.3f} [{best_m:12s}]  {pdf.name[:55]}")
        print(f"    → {new_name[:70]}")
        pdf.rename(low_dir / new_name)
        matched += 1
    else:
        print(f"  ✗ {best_s:.3f}  {pdf.name[:55]}")
        unmatched += 1

print(f"\n[done] renamed={matched}  still_unmatched={unmatched}")
print(f"         arxiv_low_relevance/ 剩余: {len(list(low_dir.glob('*.pdf')))}")
