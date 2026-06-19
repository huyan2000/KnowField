#!/usr/bin/env python3
"""
['arxiv_low_relevance/', 'non_relevant_pdf/' ] 中归档 PDF 重新扫描：
- 读取前 10 页全文（前方扫描更可能）
- 在报告 CSV 标题/摘要字段里做全文 vs 标题/摘要匹配
- 匹配 ≥ 0.75 → 移到根目录并命名为报告标准标题
- 仍不匹配 → 留在原处（期刊/综述/书籍）

用法: python3 pdf_reattempt_archive.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
import re
import shutil
import sys
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
MATCH_THRESHOLD = 0.75

# 要扫描的归档文件夹（可扩展）
ARCHIVE_FOLDERS = [
    "arxiv_low_relevance",
    "non_relevant_pdf",
]

STOP_MATCH = {
    "abstract","introduction","ieee transactions","ieee internet of things journal",
    "received","accepted","published online","journal of","proceedings of",
    "springer","elsevier","wiley","ieee","doi:","issn","isbn",
}

def normalize(s):
    s = (s or "").lower()
    s = s.replace("–","-").replace("—","-").replace("−","-")
    return re.sub(r"[^a-z0-9]+"," ",s).strip()

def compact(s):
    return re.sub(r"[^a-z0-9]+","", (s or "").lower())

def score(a, b):
    an, bn = normalize(a), normalize(b)
    if not an or not bn: return 0.0
    s = SequenceMatcher(None, an, bn).ratio()
    ac, bc = compact(a), compact(b)
    if ac and bc and (ac in bc or bc in ac):
        s = max(s, 0.98 if min(len(ac),len(bc)) >= 32 else 0.90)
    return s

def extract_fulltext(path: Path, max_pages=15) -> str:
    """读取前 max_pages 页全文"""
    try:
        reader = PdfReader(str(path))
        return "\n".join(p.extract_text() or "" for p in reader.pages[:max_pages])
    except Exception:
        return ""

def extract_arxiv_id(path: Path) -> str:
    """只接受形如 XXXX.XXXXX 的 arXiv 标识符，错误识别的单词一律返回空"""
    m = re.search(r"(\d{4}\.\d{4,5}v?\d*)", path.stem)
    return m.group(1) if m else ""


def safe_filename(title: str, arxiv_id: str = "") -> str:
    slug = re.sub(r"[^A-Za-z0-9]+","_", title.lower()).strip("_")[:80]
    if arxiv_id:
        return f"{arxiv_id}_{slug}.pdf"
    return f"{slug}.pdf"

def main():
    import argparse
    parser = argparse.ArgumentParser(description="重新扫描归档 PDF 与主报告匹配")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--threshold", type=float, default=MATCH_THRESHOLD)
    args = parser.parse_args()
    dry = args.dry_run
    thr = args.threshold

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
    RELEVANT = ["标题", "摘要"]

    total_scan = 0
    matched_out, moved = 0, 0
    all_unmatched: list[tuple[str,str,float]] = []

    for folder in ARCHIVE_FOLDERS:
        src_dir = pdf_root / folder
        if not src_dir.is_dir():
            print(f"[skip] {folder}/ 不存在")
            continue
        pdfs = sorted(src_dir.glob("*.pdf"))
        if not pdfs:
            print(f"[skip] {folder}/ 为空")
            continue

        print(f"\n[scan] {folder}/  → {len(pdfs)} PDFs")
        m_ok, m_fail = 0, 0

        for pdf in pdfs:
            total_scan += 1
            fulltext = extract_fulltext(pdf, max_pages=15)
            raw = "\n".join(l.strip() for l in fulltext.splitlines() if l.strip())

            # 清洗行（去掉版权/期刊名等噪声）
            good = []
            for ln in raw.splitlines()[:2000]:
                low = ln.lower()
                if len(ln) < 15: continue
                if re.match(r"^[\d][\d\s\.:]*$", low): continue
                if any(low.startswith(s) for s in STOP_MATCH): continue
                good.append(ln)

            # 拼 title span（前15行，最大200字符）
            title_span = ""
            for i, ln in enumerate(good[:15]):
                sp = ln
                for j in range(i+1, min(i+4, len(good))):
                    nxt = good[j]
                    if nxt is not ln:
                        sp += " " + nxt
                if len(sp) > 200:
                    break
                if len(sp) >= 15:
                    title_span = sp
                    break
            if not title_span:
                title_span = pdf.stem.replace("_"," ").replace("-"," ")

            # 全文片段（前1000字符 vs 标题；前3000字符 vs 摘要）
            first_1000  = raw[:1000]
            first_3000  = raw[:3000]
            fname_norm  = pdf.stem.replace("_"," ").replace("-"," ")
            signals = {"span": title_span, "f1000": first_1000, "f3000": first_3000, "fname": fname_norm}

            # 全局扫描
            best_overall = 0.0
            best_row_idx, best_method_label = -1, ""
            for ri, row in enumerate(report_rows):
                for f_, signal in signals.items():
                    if f_ == "f1000":
                        weight = 0.85
                        target_field = "标题"
                    elif f_ == "f3000":
                        weight = 0.80
                        target_field = "摘要"
                    else:
                        weight = 1.0
                        target_field = "标题"
                    txt = row.get(target_field, "")
                    if not txt: continue
                    s = score(signal, txt) * weight
                    if s > best_overall:
                        best_overall, best_row_idx, best_method_label = s, ri, f"{f_}→{target_field}"

            best_s = best_overall

            if best_s >= thr:
                std_title = report_rows[best_row_idx]["标题"] if best_row_idx >= 0 else ""
                new_name = safe_filename(std_title, arxiv_id=extract_arxiv_id(pdf))
                dest = pdf_root / new_name        # 移到根目录
                already = dest.resolve() == pdf.resolve()
                print(f"  ✓ {best_s:.3f} [{best_method_label:12s}] {pdf.name[:55]}")
                print(f"    → {new_name[:70]}")
                if not dry and not already:
                    shutil.move(str(pdf), str(dest))
                    m_ok += 1
                elif already:
                    m_ok += 1
                else:
                    m_ok += 1     # dry-run 状态下计数仍是成功
            else:
                print(f"  ✗ {best_s:.3f} [{best_method_label:12s}] {pdf.name[:60]}")
                all_unmatched.append((folder, pdf.name, best_s))
                m_fail += 1

        print(f"  归档: {folder}/ matched_ok={m_ok}  unmatched={m_fail}")
        moved += m_ok

    print(f"\n[总览] 扫描 {total_scan} 篇，匹配 {matched_out+moved} 篇，失败 {len(all_unmatched)} 篇")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
