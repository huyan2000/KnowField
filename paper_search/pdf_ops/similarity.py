#!/usr/bin/env python3
"""
扫描 PHD-Buyya 全库 PDF 文件名，找出相似度 >= 0.82 的配对。
187 篇 → 约 17 k 对比较 → 预计 1 s 内出结果
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import os

from utils.paths import find_pdf_root

@dataclass
class PdfEntry:
    rel: str   # 相对 PHD-Buyya/ 的路径
    stem: str  # 去扩展名的文件名（已去掉 arxiv_id 前缀）

def strip_prefix(name: str) -> str:
    stem = name
    # arXiv 格式: 20250514_2505.08377_slug → slug
    stem = re.sub(r"^\d{8}_\d{4}\.\d{4,5}v?\d*_", "", stem)
    stem = re.sub(r"^\d{8}_\d{4,5}_", "", stem)
    return stem

def norm_raw(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()

def compact_raw(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())

def sim(a: str, b: str) -> float:
    an, bn = norm_raw(a), norm_raw(b)
    if not an or not bn: return 0.0
    s = SequenceMatcher(None, an, bn).ratio()
    ac, bc = compact_raw(a), compact_raw(b)
    if ac and bc and (ac in bc or bc in ac):
        s = max(s, 0.98 if min(len(ac), len(bc)) >= 32 else 0.90)
    return s

def main():
    THR = 0.82

    env_pdf_root = os.getenv("PHD_BUYYA_DIR") or os.getenv("PAPER_PDF_DIR")
    pdf_root = Path(env_pdf_root).expanduser() if env_pdf_root else find_pdf_root(Path.cwd())
    pdfs = sorted(pdf_root.rglob("*.pdf"))
    N = len(pdfs)
    print(f"物理 PDF: {N} 篇")

    entries: list[PdfEntry] = []
    for p in pdfs:
        rel  = str(p.relative_to(pdf_root))
        stem = strip_prefix(p.stem)
        entries.append(PdfEntry(rel=rel, stem=stem))

    # O(N²) 两两扫描  187 × 187 / 2 ≈ 17 K 次比较
    print(f"两两比较: {N*(N-1)//2:,} 对\n")
    found: list[tuple[str,str,float]] = []
    seen_pairs: set[tuple[str,str]] = set()

    for i in range(N):
        if i % 40 == 0:
            print(f"  [{i}/{N}] ...", flush=True)
        for j in range(i + 1, N):
            a, b = entries[i], entries[j]
            # 快速剪枝：显著长度差 → 分数不可能高
            if abs(len(a.stem) - len(b.stem)) > 50:
                continue
            s = sim(a.stem, b.stem)
            if s >= THR:
                key = tuple(sorted([a.rel, b.rel]))
                if key not in seen_pairs:
                    seen_pairs.add(key)
                    found.append((a.rel, b.rel, s))

    if not found:
        print(f"\n[OK] 所有文件名相似度 < {THR}")
        return

    found.sort(key=lambda t: -t[2])
    print(f"\n发现 {len(found)} 对高度相似文件名（≥{THR}）:\n")
    for ra, rb, s in found:
        flag = "⚠ 疑似重复" if s >= 0.96 else "🔍 高度相似"
        print(f"  {flag}  sim={s:.3f}")
        print(f"    [{ra}]")
        print(f"    [{rb}]")
        print()

if __name__ == "__main__":
    main()
