#!/usr/bin/env python3
"""
扫描 arxiv_low_relevance/ 中 PDF（已成功重命名的文件），
用前10页全文 + 报告全局已访问确定是否属于报告条目：
匹配→移到根目录（保持当前标准文件名）
仍不匹配→不动
"""
import re, csv, shutil
from pathlib import Path
from difflib import SequenceMatcher
from pypdf import PdfReader

def normalize(s): return re.sub(r"[^a-z0-9]+"," ", (s or "").lower()).strip()
def compact(s): return re.sub(r"[^a-z0-9]+","", (s or "").lower())
def score(a, b):
    an, bn = normalize(a), normalize(b)
    if not an or not bn: return 0.0
    s = SequenceMatcher(None, an, bn).ratio()
    ac, bc = compact(a), compact(b)
    if ac and bc and (ac in bc or bc in ac):
        s = max(s, 0.98 if min(len(ac),len(bc))>=32 else 0.90)
    return s

base     = Path(__file__).resolve().parents[1]
repo     = base.parent
from utils.paths import find_pdf_root
pdf_root = find_pdf_root(repo)
low_dir  = pdf_root / "arxiv_low_relevance"
report_csv = base / "paper_search_report.csv"
report_rows = list(csv.DictReader(report_csv.open(encoding="utf-8-sig")))
TEXT_FIELDS = ["标题", "摘要"]

pdfs = sorted(low_dir.glob("*.pdf"))
print(f"[init] arxiv_low_relevance/: {len(pdfs)} PDFs\n")

def similar_pdf(pdf_path, threshold=0.70):
    try:
        r = PdfReader(str(pdf_path))
        txt = "\n".join(p.extract_text() or "" for p in r.pages[:10])
    except Exception:
        return 0.0, "", ""

    raw = "\n".join(l.strip() for l in txt.splitlines() if l.strip())
    STOP = {"abstract","introduction","received","accepted","published online","journal of","proceedings of","doi:"}
    good = []
    for ln in raw.splitlines()[:2000]:
        low = ln.lower()
        if len(ln) < 15: continue
        if re.match(r"^[\d][\d\s\.:]*$", low): continue
        if any(low.startswith(s) for s in STOP): continue
        good.append(ln)

    # title span from first 15 good lines
    span = None
    for i, ln in enumerate(good[:15]):
        sp = ln
        for j in range(i+1, min(i+4, len(good))):
            nxt = good[j]
            if nxt is not ln: sp += " " + nxt
        if 20 <= len(sp) <= 200: span = sp; break
    title_span = span or pdf_path.stem.replace("_"," ").replace("-"," ")
    full_100 = raw[:1000]
    fname    = pdf_path.stem.replace("_"," ").replace("-"," ")

    best_s, best_i, best_f = 0.0, -1, ""
    for ri, row in enumerate(report_rows):
        for f_ in TEXT_FIELDS:
            txt = row.get(f_,"")
            if not txt: continue
            for signal, w in [(title_span,1.0),(fname,1.0),(full_100,0.85)]:
                s = score(signal, txt) * w
                if s > best_s:
                    best_s, best_i, best_f = s, ri, f"{signal[:15]}"

    return best_s, report_rows[best_i]["标题"] if best_i >= 0 else "", best_f

moved, remain = 0, 0
for pdf in pdfs:
    s, rtitle, method = similar_pdf(pdf)
    if s >= 0.70:
        dest = pdf_root / pdf.name
        if not dest.exists():
            shutil.move(str(pdf), str(dest))
            print(f"  ✓ {s:.3f}  {pdf.name[:55]}")
            moved += 1
        else:
            pdf.unlink()
            print(f"  ✓ {s:.3f}  {pdf.name[:55]}  (目标已存在，删除重复)")
            moved += 1
    else:
        print(f"  — {s:.3f}  {pdf.name[:55]}")
        remain += 1

print(f"\n[done] moved/renamed→root={moved}  still_in_low_relevance={remain}")
print(f"       arxiv_low_relevance/ 剩余: {len(list(low_dir.glob('*.pdf')))}")
