#!/usr/bin/env python3
"""修复 arxiv_latest_papers/ 中重复前缀的 34 个文件

修复逻辑
─────────
当前文件名格式: word_word_rest...
其中 word 是论文标题第一个词，第二个 word 是被误作 arxiv_id 的前缀。

规则:
  case "exact": parts = [w, w, rest...]  → clean = w + "_" + "_".join(parts[2:])
  case "prefix": parts = [w, w_rest...]   → clean = w + "_" + rest[2:] (去掉重复的 w_)
"""
import re, csv
from pathlib import Path
from difflib import SequenceMatcher

def normalize(s):
    return re.sub(r"[^a-z0-9]+"," ", (s or "").lower()).strip()
def compact(s): return re.sub(r"[^a-z0-9]+","", (s or "").lower())
def score(a, b):
    an, bn = normalize(a), normalize(b)
    if not an or not bn: return 0.0
    s = SequenceMatcher(None, an, bn).ratio()
    ac, bc = compact(a), compact(b)
    if ac and bc and (ac in bc or bc in ac):
        s = max(s, 0.98 if min(len(ac),len(bc))>=32 else 0.90)
    return s

pdf_dir   = Path("../PHD-Buyya/arxiv_latest_papers")
report_csv = Path("paper_search_report.csv")
if not report_csv.exists():
    raise SystemExit("找不到 paper_search_report.csv")

report_rows = list(csv.DictReader(report_csv.open(encoding="utf-8-sig")))
report_map  = {}
for r in report_rows:
    t = r.get("标题","").strip()
    if not t: continue
    slug = re.sub(r"[^A-Za-z0-9]+","_", t.lower()).strip("_")[:80]
    report_map[slug] = t

pdfs = sorted(pdf_dir.glob("*.pdf"))
print(f"arxiv_latest_papers/ 共 {len(pdfs)} 个文件\n")

fixed, skipped = 0, 0
for pdf in pdfs:
    n = pdf.stem
    parts = n.split("_")

    # ── 判断是否重复前缀 ────────────────────────────────────
    is_d = False
    if len(parts) >= 3 and parts[0].lower() == parts[1].lower():
        is_d, mode = True, "exact"          # w_w_rest...
    elif len(parts) >= 3 and parts[1].lower().startswith(parts[0].lower() + "_"):
        is_d, mode = True, "prefix"          # w_wrest_rest...

    if not is_d:
        print(f"  — 跳过 {n[:60]}")
        skipped += 1
        continue

    # ── 构造去重后的缩写标题 ──────────────────────────────
    if mode == "exact":
        # parts = [w, w, rest1, rest2...]
        word  = parts[0]
        rest  = "_".join(parts[2:])
    else:   # "prefix"
        # parts = [w, w_rest1, rest2...]
        word  = parts[0]
        # 改成去掉第一个出现的 word_
        with_word = "_".join(parts[:2])      # e.g. "ca_hfp_..."
        rest = with_word[len(word)+1:]       # 去掉 "ca_" → "hfp_..."

    candidate = (word + " " + rest.replace("_"," ")).strip()

    # ── 在报告中匹配 ───────────────────────────────────────
    best_s, best_title = 0.0, ""
    for rslug, rtitle in report_map.items():
        s = score(candidate, rtitle)
        if s > best_s: best_s, best_title = s, rtitle

    if best_s >= 0.75:
        std_slug = re.sub(r"[^A-Za-z0-9]+","_", best_title.lower()).strip("_")[:80]
        new_name = f"{std_slug}.pdf"
        target = pdf_dir / new_name
        print(f"  ✓ {best_s:.3f}  {n[:50]}\n    → {new_name[:68]}")
        if not target.exists():
            pdf.rename(target)
        else:
            pdf.unlink()
        fixed += 1
    else:
        print(f"  ✗ {best_s:.3f}  {n[:55]}")
        skipped += 1

print(f"\n[done] fixed={fixed}  skipped={skipped}")
print(f"       arxiv_latest_papers/ 剩余: {len(list(pdf_dir.glob('*.pdf')))}")
