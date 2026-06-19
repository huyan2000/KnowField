#!/usr/bin/env python3
"""合订本/多论文 PDF 反向匹配。

针对一份本地 PDF 里包含报告中多篇论文（典型例子：Springer LNCS 合订本、IEEE
proceedings、某期 IoT-J 的多篇论文打包下载）的情况，把所有出现的论文行都
回填指向同一个本地 PDF 文件。

策略：
  1) PDF outline (TOC) —— 最干净的信号，Springer / Wiley / 大多数会议
     proceedings 都会把章节标题做成 PDF bookmark。
  2) 每章首页文本兜底 —— 若 outline 缺失/不全，回退到逐页 extract_text 抽取
     首页大字标题，再做模糊匹配。

仅返回 "匹配上的报告行 index 列表"。不修改任何文件、不写盘。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment]


# 报告标题低于这个相似度的，不算匹配。比单 PDF 1:1 对账的 0.82 略严格，
# 因为这里目的是"补遗漏"，宁可漏标不可错标。
MULTI_MATCH_THRESHOLD = 0.85

# 同一份 PDF 最多额外贡献多少个匹配（防假阳性爆炸）。
MAX_EXTRA_MATCHES_PER_PDF = 8

# 兜底文本扫描最多读多少页
MAX_PAGES_FOR_FALLBACK = 80

# Fallback 阶段为「单论文 PDF」时只扫前几页，避免命中 References 段里出现的报告论文标题
FALLBACK_PAGES_SHORT = 8

# 章节首页文本截取长度（前 N 个字符够覆盖标题）
HEAD_TEXT_LEN = 280

# 通用 outline 条目，不当论文标题处理
OUTLINE_SKIP_EXACT = {
    "title page", "preface", "foreword", "introduction",
    "table of contents", "contents", "author index",
    "subject index", "index", "references", "bibliography",
    "acknowledgments", "acknowledgements", "appendix",
    "conclusions", "conclusion", "abstract", "summary",
    "front matter", "back matter", "copyright",
    "list of figures", "list of tables", "notation",
    "discussion", "discussions", "related work", "future work",
    "evaluation", "experiments", "results", "methodology",
    "background", "preliminaries", "preliminary", "system model",
    "problem formulation", "related works", "biographies",
    "experimental evaluation", "motivation", "title",
}

# 普通论文 outline 子标题里常出现的模板词；这种 outline 条目不算论文标题候选
OUTLINE_SKIP_CONTAINS = (
    "biograph", "appendix", "experiment setup",
)

# 通用 outline 前缀（Part 1 / Chapter 5 / Section 2.3 等）
OUTLINE_SKIP_PREFIX_RE = re.compile(
    r"^(part|chapter|section|appendix|annex|paper)\s+[ivxlcdm\d]+[\.:]?\s*$",
    re.I,
)


@dataclass
class MultiPaperMatch:
    pdf_path: Path
    matched_rows: list[int] = field(default_factory=list)   # row indices (0-based)
    evidence: list[str] = field(default_factory=list)        # "outline:<title>" / "page<N>:<title>"


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower())


def _ratio(a: str, b: str) -> float:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    score = SequenceMatcher(None, na, nb).ratio()
    # 完整对称包含（两者长度近似 + 子串）才视为强匹配；
    # 不做单向子串加权，否则普通论文 outline 的小标题会误中报告中更长的论文标题
    if len(na) >= 40 and len(nb) >= 40 and abs(len(na) - len(nb)) <= 8:
        if na in nb or nb in na:
            score = max(score, 0.95)
    return score


def _is_skippable_outline_entry(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    low = t.lower()
    if low in OUTLINE_SKIP_EXACT:
        return True
    if OUTLINE_SKIP_PREFIX_RE.match(low):
        return True
    for keyword in OUTLINE_SKIP_CONTAINS:
        if keyword in low:
            return True
    # 太短的 outline 条目（< 18 字符）一般是节标题，不是论文标题
    if len(re.sub(r"[^A-Za-z]", "", t)) < 18:
        return True
    return False


def _looks_like_anthology(outline_titles: list[str]) -> bool:
    """启发式：判断 outline 是否来自合订本。

    合订本：顶层有 ≥ 2 个长 (≥ 30 字符) 的论文标题。
    普通论文：顶层都是节名 (Introduction / Related Work / Background ...) ，
              即便能逃过 SKIP_EXACT，也会因为长度短被过滤。
    """
    long_titles = [t for t in outline_titles if len(re.sub(r"[^A-Za-z]", "", t)) >= 30]
    return len(long_titles) >= 2


def extract_outline_titles(pdf_path: Path, max_depth: int = 2) -> list[str]:
    """递归读 PDF outline，返回 depth ≤ max_depth 的论文标题候选。

    过滤掉 Preface / Introduction / Part X / Chapter X 等通用条目。
    """
    if PdfReader is None:
        return []
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return []
    if not reader.outline:
        return []

    out: list[str] = []

    def walk(items, depth: int) -> None:
        if depth > max_depth:
            return
        for it in items:
            if isinstance(it, list):
                walk(it, depth + 1)
                continue
            title = getattr(it, "title", None)
            if title and not _is_skippable_outline_entry(title):
                out.append(title.strip())

    walk(reader.outline, depth=0)
    # 去重保序
    seen: set[str] = set()
    unique: list[str] = []
    for t in out:
        key = _norm(t)
        if key in seen:
            continue
        seen.add(key)
        unique.append(t)
    return unique


def _extract_chapter_head_titles(pdf_path: Path, *, max_pages: int | None = None) -> list[str]:
    """兜底：逐页取首段前 HEAD_TEXT_LEN 字符作为候选标题片段。

    这里返回的是"页首字符串"，匹配时报告标题作为这字符串的子串去找。
    """
    if PdfReader is None:
        return []
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return []
    limit = max_pages or MAX_PAGES_FOR_FALLBACK
    heads: list[str] = []
    for i, page in enumerate(reader.pages[:limit]):
        try:
            text = page.extract_text() or ""
        except Exception:
            continue
        # 取前若干字符；扁平化空白
        snippet = re.sub(r"\s+", " ", text.strip())[:HEAD_TEXT_LEN]
        if snippet:
            heads.append(snippet)
    return heads


def match_pdf_to_rows(
    pdf_path: Path,
    rows: list[dict],
    *,
    threshold: float = MULTI_MATCH_THRESHOLD,
    max_matches: int = MAX_EXTRA_MATCHES_PER_PDF,
) -> MultiPaperMatch:
    """对单份 PDF 返回它在 rows 里覆盖的论文 index 列表。

    Parameters
    ----------
    pdf_path
        本地 PDF 绝对路径
    rows
        报告全表（每行至少有 "标题" 字段）
    threshold
        模糊匹配最低相似度
    max_matches
        同一份 PDF 至多回填多少行（防 false-positive 风险）

    Returns
    -------
    MultiPaperMatch
        - matched_rows: 0-based 行 index 列表
        - evidence: 每个匹配的来源说明
    """
    result = MultiPaperMatch(pdf_path=pdf_path)
    if not rows:
        return result

    # 预备：报告标题归一化
    row_titles = [r.get("标题", "") for r in rows]
    row_norms = [_norm(t) for t in row_titles]

    matched: dict[int, str] = {}   # row idx → evidence

    # ── 阶段 1: outline ────────────────────────────────────────────────
    outline_titles = extract_outline_titles(pdf_path)
    is_anthology = _looks_like_anthology(outline_titles)
    if is_anthology:
        for ot in outline_titles:
            if len(matched) >= max_matches:
                break
            best_idx = -1
            best_score = 0.0
            for i, rt in enumerate(row_titles):
                if i in matched:
                    continue
                s = _ratio(ot, rt)
                if s > best_score:
                    best_score = s
                    best_idx = i
            if best_idx >= 0 and best_score >= threshold:
                matched[best_idx] = f"outline:{ot[:60]}"

    # ── 阶段 2: 每章首页文本兜底 ──────────────────────────────────────────
    # 仅在 outline 完全空（无 bookmark）时启用全文 fallback —— 这种情况通常
    # 是扫描版合订本或没做 TOC 的 proceedings。
    # 已有 outline 但 outline 0 匹配 = 普通论文，不做 fallback（避免误命中
    # 引言/参考文献里的报告论文标题）。
    if not matched and not outline_titles:
        heads = _extract_chapter_head_titles(pdf_path, max_pages=MAX_PAGES_FOR_FALLBACK)
        for page_idx, head in enumerate(heads):
            if len(matched) >= max_matches:
                break
            head_n = _norm(head)
            if not head_n:
                continue
            for i, rn in enumerate(row_norms):
                if i in matched:
                    continue
                # 报告标题作为页首文本的子串
                if rn and len(rn) >= 32 and rn in head_n:
                    matched[i] = f"page{page_idx + 1}:head-match"

    result.matched_rows = sorted(matched.keys())
    result.evidence = [matched[i] for i in result.matched_rows]
    return result


def find_multipaper_pdfs(
    pdf_paths: list[Path],
    rows: list[dict],
    *,
    threshold: float = MULTI_MATCH_THRESHOLD,
    max_matches: int = MAX_EXTRA_MATCHES_PER_PDF,
) -> list[MultiPaperMatch]:
    """对一组 PDF 批量做反向匹配。返回 matched_rows 非空的结果列表。"""
    results: list[MultiPaperMatch] = []
    for p in pdf_paths:
        m = match_pdf_to_rows(p, rows, threshold=threshold, max_matches=max_matches)
        if m.matched_rows:
            results.append(m)
    return results
