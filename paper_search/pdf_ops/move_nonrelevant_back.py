#!/usr/bin/env python3
"""将 non_relevant_pdf/ 中按报告标题重命名后的文件，移回 PHD-Buyya/ 根目录（如目标已存在则跳过）"""
import shutil
from pathlib import Path

buyya = Path("../PHD-Buyya")
non_rel = buyya / "non_relevant_pdf"
if not non_rel.is_dir():
    print(f"[info] {non_rel} 不存在，无需处理")
    raise SystemExit(0)

pdfs = sorted(non_rel.glob("*.pdf"))
moved, skip, fail = 0, 0, 0
for pdf in pdfs:
    dest = buyya / pdf.name
    if dest.exists():
        skip += 1
        continue
    try:
        shutil.move(str(pdf), str(dest))
        moved += 1
    except Exception as e:
        fail += 1
        print(f"  [fail] {pdf.name}: {e}")

print(f"[done] moved={moved}  skip={skip}  fail={fail}")
print(f"         non_relevant_pdf/ 剩余: {len(list(non_rel.glob('*.pdf')))} 篇")
print(f"         PHD-Buyya 根目录: {len(list(buyya.glob('*.pdf')))} 篇")
