#!/usr/bin/env python3
"""Rename PDFs in PHD-Buyya to match their paper_search_report title, or move outliers to a separate folder.

流程
────
1. 从 PDF 第一页前 40 行提取论文标题
2. 用 difflib.SequenceMatcher 和 paper_search_report.csv 每行标题做模糊匹配
3. 匹配分数 ≥ 0.82 → 用报告中的标准标题重命名 PDF
4. 匹配分数 < 0.82 → 移到 <pdf_root>/arxiv_low_relevance/ 存档
"""
from __future__ import annotations

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
    print("[fatal] 需要 pypdf：pip install pypdf", file=sys.stderr)
    raise SystemExit(1)

# ── Constants ──────────────────────────────────────────────
PDF_MIN_SIZE = 10_000          # ≤ 此值视为无效 / 未完成下载
MATCH_THRESHOLD = 0.82         # ≥ 视为匹配成功
LOW_RELEV_SUBDIR = "arxiv_low_relevance"   # 低匹配分 PDF 存放的子文件夹名

# Header / boilerplate lines to skip when extracting the title from page 1
STOP_LINES = {
    "abstract", "introduction", "arxiv", "ieee transactions", "ieee internet of things journal",
    "ieee transactions on mobile computing", "received", "accepted", "published online",
    "journal of latex class files", "journal of latex",
    "lecture notes in computer science", "lecture notes",
    "this is an electronic reprint", "electronic reprint of the original",
    "corresponding author", "commenced publication", "powered by tcpdf",
    "this material is protected by copyright",
    "research article", "review article", "original article",
    "noname manuscript", "manuscript submitted", "preprint submitted",
    "preprint", "in press",
    "published as a conference paper", "to appear in",
    "accepted for publication",
    # 机构 repository / open access cover page 标识
    "orca", "this is an open access", "cardiff university",
    "this is the author", "citation for final published",
    "publishers page", "please note",
    "changes made as a result", "this version is being",
    "this is a postprint", "this is a preprint", "this is a pre-print",
    "author accepted manuscript", "authors' final version",
    "aaltodoc", "jyu dspace",
}

# Overrides for PDFs whose first-page text is too noisy for title extraction.
KNOWN_TITLE_OVERRIDES: dict[str, str] = {
    "1-s2.0-S0950705125006069-main.pdf": "Adaptive aggregation for federated learning using representation ability based on feature alignment",
    "A_Heterogeneity-Aware_Adaptive_Federated_Learning_Framework_for_Short-Term_Forecasting_in_Electric_IoT_Systems.pdf": "A Heterogeneity-Aware Adaptive Federated Learning Framework for Short-Term Forecasting in Electric IoT Systems",
    "Federated_Learning_With_Client_Clustering_Selection_and_Quality-Aware_Model_Aggregation_2024.pdf": "Federated Learning With Client Clustering Selection and Quality-Aware Model Aggregation",
    "GossipFL_A_Decentralized_Federated_Learning_Framework_With_Sparsified_and_Adaptive_Communication.pdf": "GossipFL: A Decentralized Federated Learning Framework With Sparsified and Adaptive Communication",
    "01.pdf": "Federated Learning in IoT: A Survey on Distributed Decision Making",
    "ELEC_Zhou_etal_Two_layer_Federated_Learning_IEEE_Transactions_on_Vehicular_Technology_2021_acceptedauthormanuscript.pdf": "Two-Layer Federated Learning With Heterogeneous Model Aggregation for 6G Supported Internet of Vehicles",
}

# ── Data structures ────────────────────────────────────────
@dataclass
class PdfRecord:
    path: Path
    source_dir: str
    extracted_title: str
    matched_index: int | None = None
    matched_title: str = ""
    match_score: float = 0.0
    action: str = ""          # "renamed" | "moved_low_relevance" | "rename_failed" | "move_failed"

# ── Helpers ─────────────────────────────────────────────────
def h(v: object) -> str:
    return html.escape(str(v or ""), quote=True)


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line or "").strip()
    line = line.replace("ﬁ", "fi").replace("ﬂ", "fl")
    return line


def extract_text(path: Path, pages: int = 1) -> str:
    """Extract raw text from the first N pages of a PDF."""
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages[:pages])
    except Exception:
        return ""


# STOP_LINES 中这些前缀**额外**触发"前面的 kept 全清空"——
# 表示"前面的内容是元信息/封面页，真正论文从这之后开始"
RESET_PREFIXES = (
    "ieee transactions", "ieee internet of things",
    "journal of latex", "lecture notes",
    "noname manuscript",
    "this is an open access", "cardiff university",
    "publishers page", "this version is being",
)


def _extract_title_window(lines: list[str], window: int) -> str:
    """从 lines 前 window 行内尝试组装一个标题候选；不够长返回空。"""
    kept: list[str] = []
    for line in lines[:window]:
        low = line.lower()
        # 检测到论文期刊页眉/cover-page boundary —— 之前的 kept 都是元数据，丢弃
        if any(low.startswith(p) for p in RESET_PREFIXES):
            kept = []
            continue
        if any(low.startswith(s) for s in STOP_LINES):
            continue
        if re.match(r"^(\d+|[a-z]?\s*\d+)$", low):
            continue
        if "copyright" in low or "doi:" in low or "arxiv:" in low:
            continue
        kept.append(line)
    candidates: list[str] = []
    for line in kept[:12]:
        low = line.lower()
        if low.startswith("abstract") or "@" in line:
            break
        # 作者列表检测：含逗号 + 形如 "Word Word[N|*|†][,...]" 视为作者列表
        # 必须含逗号，避免误命中标题第二行（"Personalized Federated Learning..."）
        if "," in line and re.search(r"^[A-Z][a-z]+\s+[A-Z][A-Za-z\.\d\*†‡∗\s]*,", line) and candidates:
            break
        if len(line) < 4:
            continue
        candidates.append(line)
        joined = " ".join(candidates)
        if len(joined) > 160 or len(candidates) >= 5:
            break
    title = clean_line(" ".join(candidates))
    title = re.sub(r"\s+", " ", title).strip(" -")
    return title if len(title) >= 12 else ""


def find_title_lines(lines: list[str]) -> str:
    """三阶段窗口：40 → 500 → 1000 行。返回第一个 ≥ 12 字符的候选。
    向后兼容的"单候选"接口；多候选请用 find_title_candidates。"""
    for window in (40, 500, 1000):
        t = _extract_title_window(lines, window)
        if t:
            return t
    return ""


def find_title_candidates(lines: list[str]) -> list[str]:
    """返回所有窗口的候选；用于 best_match 多次模糊匹配兜底。"""
    seen: set[str] = set()
    out: list[str] = []
    for window in (40, 500, 1000):
        t = _extract_title_window(lines, window)
        key = (t or "").lower()
        if t and key not in seen:
            seen.add(key)
            out.append(t)
    # 抓最长的两行非垃圾连续文本（fallback：很多论文标题就是页面里最长的可见 text 块）
    candidates_long = sorted(
        [ln for ln in lines[:60] if 20 <= len(ln) <= 160
            and not any(ln.lower().startswith(s) for s in STOP_LINES)
            and "@" not in ln and "copyright" not in ln.lower()],
        key=len,
        reverse=True,
    )
    for ln in candidates_long[:3]:
        key = ln.lower()
        if key not in seen:
            seen.add(key)
            out.append(ln)
    return out


def extract_title(path: Path) -> str:
    """向后兼容：返回单个最佳标题候选。"""
    candidates = extract_title_candidates(path)
    return candidates[0] if candidates else ""


def extract_title_candidates(path: Path) -> list[str]:
    """返回所有候选标题（首页扫描 + 各窗口 + 长行）。
    供 best_match_index 多候选模糊匹配使用。"""
    if path.name in KNOWN_TITLE_OVERRIDES:
        return [KNOWN_TITLE_OVERRIDES[path.name]]
    raw = extract_text(path, pages=5)
    lines = [clean_line(x) for x in raw.splitlines() if x]
    if not lines:
        return []
    return find_title_candidates(lines)


# 候选标题里如果含这些片段，认为是噪声不可用
_BAD_TITLE_SUBSTRINGS = (
    "reprint", "copyright", "powered by", "tcpdf", "metadata",
    "manuscript no", "will be inserted by",
)


def _looks_like_title(s: str) -> bool:
    if not s:
        return False
    if len(s) < 18:
        return False
    if not re.search(r"[A-Za-z]", s):
        return False
    low = s.lower()
    if any(b in low for b in _BAD_TITLE_SUBSTRINGS):
        return False
    # 末尾以介词/冠词结尾通常是被截断的半句标题
    if re.search(r"\b(for|with|and|of|the|a|an|to|on|in|by|via|from)\s*$", low):
        return False
    # 像正文段落（包含 "that", "which" 这类从句词、含完整句号、且很长）→ 不是标题
    if len(s) > 60 and re.search(r"\b(that|which|whereas|because|however|therefore)\b", low):
        return False
    # 有句号但不是缩写点（M.D.、Ph.D. 等），通常是正文段落
    if re.search(r"[a-z]\.\s+[A-Za-z]", s) and "et al" not in low:
        return False
    return True


def extract_best_title(path: Path) -> tuple[str, str]:
    """Fallback：从 PDF / filename 里挑出最像论文标题的字符串。

    挑选策略（严格保守）：
      1) PDF 候选**第 1 个**（最像首页标题的候选）必须通过 _looks_like_title
      2) 否则直接回退 filename stem —— 候选 2/3 多半是作者列表或正文段落，
         反而不如文件名 slug 稳

    Returns
    -------
    (title, source)
        title 为空表示提取失败；source ∈ {"pdf", "filename", ""}
    """
    cands = extract_title_candidates(path)
    if cands and _looks_like_title(cands[0]):
        return cands[0], "pdf"
    fn = title_from_filename(path)
    if _looks_like_title(fn):
        return _title_case_smart(fn), "filename"
    # 最后兜底：如果 filename 长度 ≥ 18 且不像噪声，也用上（哪怕 _looks_like_title 卡掉）
    if fn and len(fn) >= 18 and re.search(r"[A-Za-z]", fn):
        return _title_case_smart(fn), "filename"
    return "", ""


def _title_case_smart(s: str) -> str:
    """对全小写的文件名 slug 做"smart Title Case"：每个单词首字母大写，
    但 of/with/in/the 等连接词保持小写（除非是句首）。"""
    if not s:
        return s
    # 已经包含大写字母（不只是 acronym 风格），保持原样
    upper_count = sum(1 for c in s if c.isupper())
    letter_count = sum(1 for c in s if c.isalpha())
    if letter_count > 0 and upper_count / letter_count > 0.05:
        return s
    minor = {"a", "an", "the", "and", "or", "but", "of", "for", "in",
             "on", "at", "to", "by", "with", "from", "as", "vs", "via"}
    out: list[str] = []
    for i, word in enumerate(s.split()):
        if not word:
            out.append(word)
            continue
        lw = word.lower()
        if i > 0 and lw in minor:
            out.append(lw)
        else:
            out.append(word[0].upper() + word[1:].lower())
    return " ".join(out)


def title_from_filename(path: Path) -> str:
    name = path.stem
    # 浏览器重复下载副本: " (1)" / " (2)" / 末尾的 _1 / _2 之类
    name = re.sub(r"\s*\(\d+\)\s*$", "", name)
    name = re.sub(r"_v?\d+$", "", name)
    # 老命名：日期前缀
    name = re.sub(r"^\d+_\d{4}_\d+_", "", name)
    name = re.sub(r"_[0-9a-f]{8}$", "", name)
    name = re.sub(r"^\d{8}_\d{4}\.\d+v?\d*_", "", name)
    # 纯 arxiv id (如 "2403.08798v1") → 没法救
    name = re.sub(r"^\d{4}\.\d+v?\d*$", "", name)
    # arxiv_id 前缀残留 (如 "2403.08798v1_self_adaptive_...")，剥掉前面的 id
    name = re.sub(r"^\d{4}\.\d+v?\d*_+", "", name)
    # 出版社/期刊归档前缀（JYU/Aalto ELEC_、IEEE_、acm_、etc）
    name = re.sub(r"^(ELEC|MATH|PHYS|CS|IEEE|ACM)_+", "", name, flags=re.I)
    # 作者前缀（如 ELEC_Zhou_etal_）
    name = re.sub(r"^[A-Z][a-z]+_etal_", "", name)
    # 后缀：_acceptedauthormanuscript、_preprint、_revised、_camera ready
    name = re.sub(
        r"_(accepted[_\s]?author[_\s]?manuscript|preprint|postprint|revised|final|camera[_\s]?ready|author[_\s]?accepted)$",
        "",
        name,
        flags=re.I,
    )
    name = name.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", name).strip()


def safe_filename(title: str, arxiv_id: str = "") -> str:
    """Build a clean filename from a report title.

    保留报告标题原大小写，把不安全字符替换为空格，多余空白合并。
    `arxiv_id` 参数仅为向后兼容；不再写入文件名。
    """
    # 把 windows/mac/linux 文件系统不安全的字符替换为空格
    # （冒号、斜杠、问号、星号、引号、尖括号、管道、换行等）
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", title).strip()
    # 多余空白合并
    cleaned = re.sub(r"\s+", " ", cleaned)
    # 截断防止超过文件系统单文件名长度上限
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rstrip()
    return f"{cleaned}.pdf"


def best_match_index(
    candidates: list[str] | str,
    report_titles: list[str],
    *,
    filename_title: str = "",
) -> tuple[int | None, float, str]:
    """Return (row_index, score, method) best matching report title.

    candidates 可以是单个字符串或字符串列表（多个候选轮流跑）。
    会同时把 filename_title 加入候选；取所有候选里的最高分。
    """
    if isinstance(candidates, str):
        candidates = [candidates]
    pool: list[tuple[str, str]] = []
    seen: set[str] = set()
    for c in candidates:
        if not c:
            continue
        key = c.lower()
        if key in seen:
            continue
        seen.add(key)
        pool.append((c, "pdf-candidate"))
    if filename_title:
        key = filename_title.lower()
        if key not in seen:
            seen.add(key)
            pool.append((filename_title, "filename"))

    best_i = None
    best_s = 0.0
    best_method = "no_match"
    for src, method in pool:
        en = normalize(src)
        ec = re.sub(r"[^a-z0-9]+", "", src.lower())
        if not en:
            continue
        for i, rtitle in enumerate(report_titles):
            rn = normalize(rtitle)
            rc = re.sub(r"[^a-z0-9]+", "", rtitle.lower())
            if not rn:
                continue
            score = SequenceMatcher(None, en, rn).ratio()
            if ec and rc and (ec in rc or rc in ec):
                score = max(score, 0.98 if min(len(ec), len(rc)) >= 32 else 0.90)
            if score > best_s:
                best_i, best_s, best_method = i, score, method
    if best_s >= MATCH_THRESHOLD:
        return best_i, best_s, best_method
    return None, best_s, "no_match"


def h(v: object) -> str:
    return html.escape(str(v or ""), quote=True)


def write_csv(rows: list[dict], path: Path) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


# ── Main ───────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="PDF 按报告标题重命名 / 低匹配分移出")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印操作计划，不实际移动或重命名文件")
    parser.add_argument("--scope", choices=["arxiv", "all"], default="all",
                        help="all = 整个 PDF 根目录（默认）；arxiv = 只处理 arxiv_latest_papers/")
    parser.add_argument("--archive-unmatched", action="store_true",
                        help="未匹配上报告的 PDF 移到 arxiv_low_relevance/（默认保留原位）")
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parents[1]
    repo = base.parent
    dry_run = args.dry_run

    if dry_run:
        print("[dry-run] 只预览，不修改任何文件")
    report_csv = base / "paper_search_report.csv"
    if not report_csv.exists():
        print(f"[error] 找不到主报告: {report_csv}")
        return 1

    # 1. Load report titles
    report_rows = list(csv.DictReader(report_csv.open(encoding="utf-8-sig", newline="")))
    report_titles = [r.get("标题", "") for r in report_rows]

    # 2. Locate source PDF folder
    try:
        from utils.paths import find_pdf_root
        pdf_root = find_pdf_root(repo)
    except Exception as exc:
        print(f"[error] 无法定位 PDF 根目录: {exc}")
        return 1
    if args.scope == "all":
        src_dir = pdf_root
        src_label = pdf_root.name
    else:
        src_dir = pdf_root / "arxiv_latest_papers"
        src_label = "arxiv_latest_papers"
    if not src_dir.is_dir():
        print(f"[error] 找不到 PDF 文件夹: {src_dir}")
        return 1

    # 3. Index PDFs
    # 当 scope=all 时递归扫子目录（如 arxiv_latest_papers/, arxiv_low_relevance/）
    # 当 scope=arxiv 时本来 src_dir 就是 arxiv_latest_papers/，平铺扫即可
    if args.scope == "all":
        pdfs = sorted(src_dir.rglob("*.pdf"))
    else:
        pdfs = sorted(src_dir.glob("*.pdf"))
    print(f"[scan] {src_dir} → {len(pdfs)} PDFs")

    # 4. Extract + Match each PDF
    records: list[PdfRecord] = []
    for pdf_path in pdfs:
        title_list = extract_title_candidates(pdf_path)
        fn_title = title_from_filename(pdf_path)
        idx, score, method = best_match_index(title_list, report_titles, filename_title=fn_title)
        primary_title = title_list[0] if title_list else fn_title
        r = PdfRecord(path=pdf_path, source_dir=src_label,
                       extracted_title=primary_title,
                       matched_index=(idx + 1) if idx is not None else None,
                       matched_title=report_titles[idx] if idx is not None else "",
                       match_score=score,
                       action="")
        records.append(r)

    matched = [r for r in records if r.matched_index is not None]
    unmatched = [r for r in records if r.matched_index is None]

    # 5. Rename matched PDFs
    ARXIV_ID_RE = re.compile(r"(\d{4}\.\d{4,5}v?\d*)")
    renamed_ok, renamed_fail = 0, 0
    for r in matched:
        # 安全提取 arxiv_id：只接受形如 "XXXX.XXXXX" 的真实 arXiv 标识符
        m_ax = ARXIV_ID_RE.search(r.path.stem)
        arxiv_id = m_ax.group(1) if m_ax else ""
        new_name = safe_filename(r.matched_title, arxiv_id=arxiv_id)
        # 文件保持在它原来的子目录里，不要拉到 pdf_root 根目录
        dest = r.path.parent / new_name
        if dest == r.path:
            r.action = "already_named"
            renamed_ok += 1
            continue
        if dest.exists():
            # 同目录已经有同名文件——可能是该论文的另一个副本
            # 比较文件大小：相同则原副本删除（这是更稳的 md5 判定的近似）
            if r.path.stat().st_size == dest.stat().st_size:
                if dry_run:
                    r.action = "duplicate_will_remove"
                    renamed_ok += 1
                    continue
                try:
                    r.path.unlink()
                    r.action = "duplicate_removed"
                    renamed_ok += 1
                    continue
                except Exception as exc:
                    print(f"  [duplicate cleanup failed] {r.path.name}: {exc}")
                    r.action = "duplicate_cleanup_failed"
                    continue
            else:
                # 同名不同大小：不要动，避免误删
                r.action = "duplicate_of_existing"
                continue
        if dry_run:
            r.action = "renamed"
            renamed_ok += 1
            continue
        try:
            r.path.rename(dest)
            r.action = "renamed"
            renamed_ok += 1
        except Exception as exc:
            print(f"  [rename failed] {r.path.name}: {exc}")
            r.action = "rename_failed"
            renamed_fail += 1

    # 5b. Fallback rename for unmatched files that have a usable PDF/filename title
    # 目的：arxiv 爬虫抓到但报告里没有的论文，仍然按提取出的标题就地重命名
    # 排除 arxiv_low_relevance/ — 低相关度归档区里的命名约定保留
    # 排除 ISBN 文件名（合订本，靠 multipaper 处理而非 rename）
    fallback_renamed = 0
    remaining_unmatched: list[PdfRecord] = []
    isbn_pattern = re.compile(r"^\d{3}-\d-\d+-\d+-\d", re.I)   # 978-3-642-... ISBN-13
    for r in unmatched:
        try:
            rel = r.path.relative_to(pdf_root)
        except ValueError:
            rel = r.path
        # 跳过 arxiv_low_relevance/ 子目录 — 那里专门归档低质量文件
        if rel.parts and rel.parts[0] == LOW_RELEV_SUBDIR:
            remaining_unmatched.append(r)
            continue
        # 跳过 ISBN 命名的合订本 — 不该按某一篇论文重命名
        if isbn_pattern.match(r.path.stem):
            remaining_unmatched.append(r)
            continue
        title, source = extract_best_title(r.path)
        if not title:
            remaining_unmatched.append(r)
            continue
        new_name = safe_filename(title)
        dest = r.path.parent / new_name
        if dest == r.path:
            r.action = "already_named"
            fallback_renamed += 1
            continue
        if dest.exists():
            # 同目录已经有同名文件（可能是别的副本）—— 不动，让 dedup 阶段处理
            remaining_unmatched.append(r)
            continue
        if dry_run:
            r.action = f"renamed_from_{source}"
            r.matched_title = title   # 用于 audit 显示
            fallback_renamed += 1
            continue
        try:
            r.path.rename(dest)
            r.action = f"renamed_from_{source}"
            r.matched_title = title
            fallback_renamed += 1
        except Exception as exc:
            print(f"  [fallback rename failed] {r.path.name}: {exc}")
            remaining_unmatched.append(r)

    unmatched = remaining_unmatched

    # 6. Move unmatched PDFs (only if --archive-unmatched)
    low_dir = pdf_root / LOW_RELEV_SUBDIR
    moved_ok, moved_fail = 0, 0
    if args.archive_unmatched:
        for r in unmatched:
            low_dir.mkdir(parents=True, exist_ok=True)
            dest = low_dir / r.path.name
            if dest.exists():
                r.action = "moved_low_relevance"
                moved_ok += 1
                continue
            if dry_run:
                r.action = "moved_low_relevance"
                moved_ok += 1
                continue
            try:
                shutil.move(str(r.path), str(dest))
                r.action = "moved_low_relevance"
                moved_ok += 1
            except Exception as exc:
                print(f"  [move failed] {r.path.name}: {exc}")
                r.action = "move_failed"
                moved_fail += 1
    else:
        for r in unmatched:
            r.action = "skipped_unmatched"

    # 7. Summary
    print(f"\n[result]")
    print(f"  matched (renamed)       : {renamed_ok}")
    print(f"  renamed_fail            : {renamed_fail}")
    print(f"  fallback (PDF/filename) : {fallback_renamed}")
    if args.archive_unmatched:
        print(f"  unmatched (moved)       : {moved_ok}")
        print(f"  move_failed             : {moved_fail}")
    else:
        print(f"  unmatched (kept)        : {len(unmatched)}")

    # 8. Write audit CSV
    out_rows = []
    for r in records:
        action_label = {
            "renamed": "已按报告标题重命名",
            "renamed_from_pdf": "已按 PDF 提取标题重命名",
            "renamed_from_filename": "已按文件名重命名",
            "already_named": "文件名已规范",
            "duplicate_removed": "重复副本已删除（同大小）",
            "duplicate_will_remove": "重复副本将删除（dry-run）",
            "duplicate_of_existing": "目标名已被占（不同大小，未动）",
            "duplicate_cleanup_failed": "重复副本删除失败",
            "moved_low_relevance": f"已移入{LOW_RELEV_SUBDIR}/",
            "rename_failed": "重命名失败",
            "move_failed": "移动失败",
            "skipped_unmatched": "未匹配，原位保留",
        }.get(r.action, r.action)
        out_rows.append({
            "原PDF文件名": r.path.name,
            "提取标题": r.extracted_title,
            "匹配报告标题": r.matched_title,
            "匹配序号": str(r.matched_index or ""),
            "匹配分数": f"{r.match_score:.3f}",
            "操作": action_label,
        })
    audit_path = base / "pdf_rename_audit.csv"
    write_csv(out_rows, audit_path)
    print(f"\n[audit] 写入 {audit_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
