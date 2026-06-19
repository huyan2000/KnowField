#!/usr/bin/env python3
"""
处理 non_relevant_pdf/ 中剩余 PDF：
- 阈值放宽到 0.75（三路评估器确认这 34 篇有 22 篇可达 0.75+）
- 匹配 → 按报告标题重命名 + 移回根目录
- 仍不匹配 → 移到 arxiv_low_relevance/

用法：
  python3 pdf_reattempt_nonrelevant.py --dry-run
  python3 pdf_reattempt_nonrelevant.py
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import shutil
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:
    PdfReader = None
if PdfReader is None:
    print("[fatal] pypdf 不可用", file=sys.stderr)
    raise SystemExit(1)

PDF_MIN_SIZE = 10_000
MATCH_THRESHOLD = 0.75         # 三路评估确认此阈值有效
LOW_RELEV_SUBDIR = "arxiv_low_relevance"

STOP_LINES = {
    "abstract","introduction","arxiv","ieee transactions","received","accepted","published online",
}
KNOWN_TITLE_OVERRIDES: dict[str, str] = {}


def h(v): return html.escape(str(v or ""), quote=True)
def normalize(t): return re.sub(r"\s+"," ",re.sub(r"[^a-z0-9]+"," ",t.lower())).strip()
def compact(t): return re.sub(r"[^a-z0-9]+","", t.lower())
def clean_line(l): return re.sub(r"\s+"," ",l or "").strip().replace("ﬁ","fi").replace("ﬂ","fl")


def extract_text(path, pages=5):
    try:
        reader = PdfReader(str(path))
        return "\n".join(p.extract_text() or "" for p in reader.pages[:pages])
    except Exception:
        return ""


def find_title_lines(lines: list[str]) -> str:
    STOP = STOP_LINES
    for window in (40, 500, 1000):
        kept, cands = [], []
        for line in lines[:window]:
            low = line.lower()
            if any(low.startswith(s) for s in STOP): continue
            if re.match(r"^(\d+|[a-z]?\s*\d+)$", low): continue
            if "copyright" in low or "doi:" in low or "arxiv:" in low: continue
            kept.append(line)
        for line in kept[:12]:
            low = line.lower()
            if low.startswith("abstract") or "@" in line: break
            if re.match(r"^[A-Z][a-z]+\s+[A-Z]", line) and cands: break
            if len(line) < 4: continue
            cands.append(line)
            if len(" ".join(cands)) > 160 or len(cands) >= 5: break
        t = clean_line(" ".join(cands)).strip(" -")
        if len(t) >= 12: return t
    return ""


def extract_title(path: Path) -> str:
    if path.name in KNOWN_TITLE_OVERRIDES:
        return KNOWN_TITLE_OVERRIDES[path.name]
    raw = extract_text(path, pages=5)
    lines = [clean_line(x) for x in raw.splitlines() if x.strip()]
    if not lines:
        return path.stem.replace("_"," ").replace("-"," ")
    t = find_title_lines(lines)
    return t if t else path.stem.replace("_"," ").replace("-"," ")


def title_from_filename(path: Path) -> str:
    name = path.stem
    for pat in [r"^\d+_\d{4}_\d+_", r"_\d{8}$", r"^\d{8}_\d{4}\.\d+v?\d*_", r"^\d{4}\.\d+v?\d*$"]:
        name = re.sub(pat, "", name)
    return re.sub(r"\s+"," ",name.replace("_"," ").replace("-"," ")).strip()


def extract_arxiv_id(path: Path) -> str:
    """Robust：只接受形如 XXXX.XXXXX 的 arXiv 标识符，错误识别的单词一律返回空"""
    m = re.search(r"(\d{4}\.\d{4,5}v?\d*)", path.stem)
    return m.group(1) if m else ""

def safe_filename(title: str, arxiv_id: str = "") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+","_", title.lower()).strip("_")[:80]
    if arxiv_id:
        return f"{arxiv_id}_{slug}.pdf"
    return f"{slug}.pdf"


def fuzzy_score(a: str, b: str) -> float:
    an, bn = normalize(a), normalize(b)
    if not an or not bn: return 0.0
    s = SequenceMatcher(None, an, bn).ratio()
    ac, bc = compact(a), compact(b)
    if ac and bc and (ac in bc or bc in ac):
        s = max(s, 0.98 if min(len(ac), len(bc)) >= 32 else 0.90)
    return s


def main():
    parser = argparse.ArgumentParser(description="重新对 non_relevant_pdf 做全局报告匹配")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不移动或重命名")
    parser.add_argument("--threshold", type=float, default=MATCH_THRESHOLD, help="匹配阈值 (默认0.75)")
    args = parser.parse_args()
    dry = args.dry_run
    threshold = args.threshold

    base = Path(__file__).resolve().parents[1]
    repo = base.parent
    report_csv = base / "paper_search_report.csv"
    if not report_csv.exists():
        print(f"[error] {report_csv}", file=sys.stderr)
        return 1

    try:
        from utils.paths import find_pdf_root
        pdf_root = find_pdf_root(repo)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    report_rows = list(csv.DictReader(report_csv.open(encoding="utf-8-sig", newline="")))
    src_dir = pdf_root / "non_relevant_pdf"
    low_dir = pdf_root / LOW_RELEV_SUBDIR
    if not src_dir.is_dir():
        print(f"[error] {src_dir}")
        return 1

    pdfs = sorted(src_dir.glob("*.pdf"))
    print(f"[init] src={src_dir}  pdfs={len(pdfs)}  threshold={threshold}")

    RELEVANT = ["标题", "摘要"]

    matched, unmatched = 0, 0
    for pdf in pdfs:
        # 提取三路信号
        try:
            reader = PdfReader(str(pdf))
            raw_pages = "\n".join(p.extract_text() or "" for p in reader.pages[:5])
        except Exception:
            raw_pages = ""
        raw = "\n".join(l.strip() for l in raw_pages.splitlines() if l.strip())
        STOP_MATCH = {"abstract","introduction","received","accepted","published online","journal of","proceedings of","doi:"}
        good_lines = [l for l in raw.splitlines()[:1000]
                      if len(l) >= 15 and not re.match(r"^[\d][\d\s\.:]*$", l.lower())
                      and not any(l.lower().startswith(s) for s in STOP_MATCH)]

        # span
        title_span = ""
        for i, ln in enumerate(good_lines[:15]):
            sp = ln
            for j in range(i+1, min(i+4, len(good_lines))):
                nxt = good_lines[j]
                if nxt is not ln:
                    sp += " " + nxt
            if len(sp) > 200: break
            if len(sp) >= 15:
                title_span = sp
                break
        if not title_span:
            title_span = pdf.stem.replace("_"," ").replace("-"," ")
        first_500 = raw[:500]

        # 全局扫描全部544行报告
        best_s, best_idx, best_method = 0.0, -1, ""
        for ri, row in enumerate(report_rows):
            row_texts = {f: row.get(f,"") for f in RELEVANT if row.get(f,"")}
            for f, txt in row_texts.items():
                s = fuzzy_score(title_span, txt)
                if s > best_s:
                    best_s, best_idx, best_method = s, ri, f"span→{f}"
            for f, txt in row_texts.items():
                s = fuzzy_score(first_500, txt) * 0.8
                if s > best_s:
                    best_s, best_idx, best_method = s, ri, f"p500→{f}"
            fname = pdf.stem.replace("_"," ").replace("-"," ")
            for f, txt in row_texts.items():
                s = fuzzy_score(fname, txt)
                if s > best_s:
                    best_s, best_idx, best_method = s, ri, f"fname→{f}"

        # 打印 match 系数
        if best_s >= threshold:
            std_title = report_rows[best_idx]["标题"] if best_idx >= 0 else ""
            new_name = safe_filename(std_title, arxiv_id=extract_arxiv_id(pdf))
            dest = src_dir / new_name
            already = dest.resolve() == pdf.resolve()
            print(f"  ✓ {best_s:.3f} [{best_method}] {pdf.name[:55]} → {new_name[:70]}")
            if not dry and not already:
                pdf.rename(dest)
            matched += 1
        else:
            dest = low_dir / pdf.name
            print(f"  ✗ {best_s:.3f} [{best_method}] {pdf.name[:60]}")
            if not dry:
                low_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(pdf), str(dest))
            unmatched += 1

    print(f"\n[done] matched={matched}  unmatched={unmatched}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
