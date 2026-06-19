#!/usr/bin/env python3
"""
共享 PDF 重复检测与去重逻辑，供 build_unified_paper_report.py 和
build_missing_downloads_report.py 在每次生成报告前调用。
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path


@dataclass
class DupGroup:
    slug: str
    paths: list[Path]
    kept: Path
    removed: list[Path]


# --------------- helpers (exactly matching pdf_find_similar.py) -----------------

def strip_prefix(name: str) -> str:
    """去掉日期_arxivid_前缀，用于 slug 分组"""
    stem = name
    # 浏览器重复下载的 "xxx (1)" / "xxx (2)" 后缀
    stem = re.sub(r"\s*\(\d+\)\s*$", "", stem)
    stem = re.sub(r"^\d{8}_\d{4}\.\d{4,5}v?\d*_", "", stem)
    stem = re.sub(r"^\d{8}_\d{4,5}_", "", stem)
    return stem


def norm_raw(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def compact_raw(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", s.lower())


def sim(a: str, b: str) -> float:
    an, bn = norm_raw(a), norm_raw(b)
    if not an or not bn:
        return 0.0
    s = SequenceMatcher(None, an, bn).ratio()
    ac, bc = compact_raw(a), compact_raw(b)
    if ac and bc and (ac in bc or bc in ac):
        s = max(s, 0.98 if min(len(ac), len(bc)) >= 32 else 0.90)
    return s


# --------------- core logic -----------------------------------------------------

def dedup_pdfs(pdf_root: Path, dry_run: bool = False) -> dict[str, int]:
    """扫描 pdf_root 下所有 PDF，按 strip_prefix slug 精确去重。

    策略：每个 slug 组内保留「最深文件夹 + 最大文件」，删除其余副本。

    Returns
    -------
    dict
        {
          "dup_groups": 重复组数,
          "to_delete":  待删除文件数,
          "deleted":    实际删除数,
          "fail":       删除失败数,
          "total_after":剩余总 PDF 数,
        }
    """
    pdfs = sorted(pdf_root.rglob("*.pdf"))
    N = len(pdfs)

    duplicates_by_slug: dict[str, list[Path]] = defaultdict(list)
    for p in pdfs:
        slug = strip_prefix(p.stem)
        duplicates_by_slug[slug].append(p)

    to_delete: list[Path] = []
    seen_slugs: set[str] = set()

    for slug, group in duplicates_by_slug.items():
        if len(group) == 1:
            continue
        best = max(group, key=lambda p: (
            len(p.relative_to(pdf_root).parts), p.stat().st_size
        ))
        to_delete.extend([p for p in group if p != best])
        seen_slugs.add(slug)

    dup_groups = len(seen_slugs)

    deleted, fail = 0, 0
    if not dry_run and to_delete:
        for p in to_delete:
            try:
                p.unlink()
                deleted += 1
            except Exception:
                fail += 1

    final = len(list(pdf_root.rglob("*.pdf")))
    return {
        "dup_groups": dup_groups,
        "to_delete": len(to_delete),
        "deleted": deleted,
        "fail": fail,
        "total_after": final,
    }
