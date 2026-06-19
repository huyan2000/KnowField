#!/usr/bin/env python3
"""重新整理 PHD-Buyya 所有 PDF：匹配报告标题 → 按标题重命名；不匹配 → 移动
add_thesis_review.py 特別處理：
* <pdf_root>/20240825_4089_survey_on_xxx 系列手稿 → 移到 PHD-Buyya/thesis_review/
* <pdf_root>/ 散落 PDF（非 arxiv_latest_papers/） → 如匹配报告则重命名并归位，不匹配则移到低相关性
* batch5 批量手稿 → 移到 PHD-Buyya/batch5_thesis_papers/

政策
────
1. arxiv_latest_papers/     → 只保留論文已匹配的 PDF
2. arxiv_low_relevance/      → PDF 存在但無法與 report 匹配
3. thesis_review/            → 草稿 / 手稿 / 教師提供的review_paper
4. batch5_thesis_papers/     → batch5 系列草稿
5. PHD-Buyya 根目录散落的其他 PDF → 同样按匹配逻辑处置

用法
─────
  python3 add_thesis_review.py [--dry-run]
"""
from __future__ import annotations

import argparse
import csv
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

# ── 配置 ───────────────────────────────────────────────────────
PDF_MIN_SIZE = 10_000
MATCH_THRESHOLD = 0.75         # 三路综合匹配的通过阈值

LOW_RELEV_SUBDIR   = "arxiv_low_relevance"
LOW_RELEV_ALL      = "non_relevant_pdf"
THESIS_SUBDIR      = "thesis_review"
BATCH5_SUBDIR      = "batch5_thesis_papers"

# ── 标题提取（同 pdf_rename_and_sort.py 逻辑）─────────────────
STOP_LINES_ = {
    "abstract", "introduction", "arxiv", "ieee transactions",
    "received", "accepted", "published online",
}

KNOWN_OVERRIDES: dict[str, str] = {
    "1-s2.0-S0950705125006069-main.pdf":
        "Adaptive aggregation for federated learning using representation ability based on feature alignment",
    "A_Heterogeneity-Aware_Adaptive_Federated_Learning_Framework_for_Short-Term_Forecasting_in_Electric_IoT_Systems.pdf":
        "A Heterogeneity-Aware Adaptive Federated Learning Framework for Short-Term Forecasting in Electric IoT Systems",
    "Federated_Learning_With_Client_Clustering_Selection_and_Quality-Aware_Model_Aggregation_2024.pdf":
        "Federated Learning With Client Clustering Selection and Quality-Aware Model Aggregation",
    "GossipFL_A_Decentralized_Federated_Learning_Framework_With_Sparsified_and_Adaptive_Communication.pdf":
        "GossipFL: A Decentralized Federated Learning Framework With Sparsified and Adaptive Communication",
}


# ── 数据结构 ──────────────────────────────────────────────────
@dataclass
class PdfRecord:
    path: Path
    category: str          # "arxiv_latest" | "thesis_review" | "batch5" | "orphan"
    extracted_title: str = ""
    filename_kind: str = ""


# ── 文本处理 ──────────────────────────────────────────────────
def clean_line(line: str) -> str:
    line = re.sub(r"\s+", " ", line or "").strip()
    return line.replace("ﬁ", "fi").replace("ﬂ", "fl")


def extract_text(path: Path, pages: int = 5) -> str:
    if PdfReader is None:
        return ""
    try:
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages[:pages])
    except Exception:
        return ""


def _title_from_lines(lines: list[str]) -> str:
    """给定清洗后行列表，分三阶段搜索窗口提取标题。"""
    kept, candidates = [], []

    # ── helper: 从 kept 行中拼出标题 ────────────────────────
    def _candidates_from(kept_lines: list[str]) -> str:
        cands: list[str] = []
        for line in kept_lines[:12]:
            low = line.lower()
            if low.startswith("abstract") or "@" in line:
                break
            if re.match(r"^[A-Z][a-z]+\s+[A-Z]", line) and cands:
                break
            if len(line) < 4:
                continue
            cands.append(line)
            joined = " ".join(cands)
            if len(joined) > 160 or len(cands) >= 5:
                break
        title = clean_line(" ".join(cands))
        return re.sub(r"\s+", " ", title).strip(" -")

    for window in (40, 500, 1000):
        kept = []
        for line in lines[:window]:
            low = line.lower()
            if any(low.startswith(s) for s in STOP_LINES_):
                continue
            if re.match(r"^(\d+|[a-z]?\s*\d+)$", low):
                continue
            if "copyright" in low or "doi:" in low or "arxiv:" in low:
                continue
            kept.append(line)
        title = _candidates_from(kept)
        if len(title) >= 12:
            return title
    return ""


def extract_title(path: Path) -> str:
    if path.name in KNOWN_OVERRIDES:
        return KNOWN_OVERRIDES[path.name]
    raw = extract_text(path, pages=5)
    lines = [clean_line(l) for l in raw.splitlines() if l.strip()]
    if not lines:
        return path.stem  # fallback 文件名
    title = _title_from_lines(lines)
    return title if title else path.stem


def title_from_filename(path: Path) -> str:
    name = path.stem
    name = re.sub(r"^\w+/(\d{8})_(\d{4}\.\d+)", "", name)
    name = re.sub(r"^\d{8}_\d{4}\.\d+v?\d*_", "", name)
    name = name.replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", name).strip()


# ── 分类规则 ──────────────────────────────────────────────────
THESIS_DATE_PATTERN = re.compile(r"^\d{8}_\d{4,5}_")
BATCH5_DATE_PATTERN = re.compile(r"^\d{8}_\d{5}_")
BATCH5_NAME = re.compile(r"(?i)batch.?5|thesis_review|thesis_papers|thesis_rev")


def classify_pdf(path: Path, buyya_root: Path) -> str:
    """返回 category: 'thesis_review' | 'batch5' | 'arxiv_latest' | 'low_relevance' 等"""
    name = path.name
    rel = path.relative_to(buyya_root) if path.is_relative_to(buyya_root) else Path(name)
    parent = str(rel.parent) if rel.parent != Path(".") else ""

    # thesis_review 手稿日期前缀
    if THESIS_DATE_PATTERN.match(name) or BATCH5_DATE_PATTERN.match(name):
        return "thesis_review"
    # 区分 batch5 子文件夹名称
    if BATCH5_NAME.search(parent) or BATCH5_NAME.search(name):
        return "batch5"
    # 散落在根目录的 PDF（非 arxiv_latest_papers/）
    if parent not in ("arxiv_latest_papers", LOW_RELEV_SUBDIR, THESIS_SUBDIR, BATCH5_SUBDIR):
        return "orphan"
    return "orphan"


# ── 匹配主报告 ────────────────────────────────────────────────
def load_report_titles(csv_path: Path) -> list[str]:
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        return [r.get("标题", "") for r in csv.DictReader(fh)]


def fuzzy_score(extracted: str, report: str) -> float:
    en = normalize(extracted)
    rn = normalize(report)
    if not en or not rn:
        return 0.0
    s = SequenceMatcher(None, en, rn).ratio()
    ec = re.sub(r"[^a-z0-9]+", "", extracted.lower())
    rc = re.sub(r"[^a-z0-9]+", "", report.lower())
    if ec and rc and (ec in rc or rc in ec):
        s = max(s, 0.98 if min(len(ec), len(rc)) >= 32 else 0.90)
    return s


def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text)).strip()


# ── 主流程 ───────────────────────────────────────────────────
def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    base   = Path(__file__).resolve().parents[1]
    repo   = base.parent
    dry    = args.dry_run

    try:
        from utils.paths import find_pdf_root
        pdf_root = find_pdf_root(repo)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    report_csv = base / "paper_search_report.csv"
    if not report_csv.exists():
        print(f"[error] {report_csv}", file=sys.stderr)
        return 1

    report_rows = list(csv.DictReader(report_csv.open(encoding="utf-8-sig", newline="")))
    print(f"[init] report_rows={len(report_rows)}  pdf_root={pdf_root}")

    # ── 收集所有待处理 PDF ────────────────────────────────────
    # 策略 1：PHD-Buyya/ 根目录所有散落 PDF
    top_pdfs = sorted(pdf_root.glob("*.pdf"))

    # 策略 2：按文件名前缀匹配 thesis_review / batch5 手稿
    thesis_glob = sorted(pdf_root.glob(f"{THESIS_SUBDIR}/*.pdf"))
    batch5_glob  = sorted(pdf_root.glob(f"{BATCH5_SUBDIR}/*.pdf"))

    # 合并去重
    seen: set[Path] = set()
    records: list[PdfRecord] = []

    def add(path: Path, cat: str) -> None:
        rp = path.resolve()
        if rp in seen:
            return
        seen.add(rp)
        records.append(PdfRecord(path=path, category=cat))

    for p in top_pdfs:
        add(p, classify_pdf(p, pdf_root))
    for p in thesis_glob:
        add(p, "thesis_review")
    for p in batch5_glob:
        add(p, "batch5")

    print(f"[scan] 待处理 PDF: {len(records)}")

    # ── 分类操作 ───────────────────────────────────────────────
    thesis_dir = pdf_root / THESIS_SUBDIR
    batch5_dir  = pdf_root / BATCH5_SUBDIR
    low_dir     = pdf_root / LOW_RELEV_ALL

    renamed, moved_thesis, moved_batch5, moved_low, skipped = 0, 0, 0, 0, 0

    for r in records:
        if r.category == "thesis_review":
            dest = thesis_dir / r.path.name
            if dry:
                pass
            else:
                thesis_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(r.path), str(dest))
            r.filename_kind = "thesis_review_original"
            moved_thesis += 1

        elif r.category == "batch5":
            dest = batch5_dir / r.path.name
            if dry:
                pass
            else:
                batch5_dir.mkdir(parents=True, exist_ok=True)
                shutil.move(str(r.path), str(dest))
            r.filename_kind = "batch5_original"
            moved_batch5 += 1

        else:
            # ═══ 鲁棒匹配：3 路信号综合 ═══════════════════════════
            # 读取前5页全文，同时对比报告标题+摘要
            try:
                reader_pdf = PdfReader(str(r.path))
                raw_pages = "\n".join(p.extract_text() or "" for p in reader_pdf.pages[:5])
            except Exception:
                raw_pages = ""
            raw = "\n".join(l.strip() for l in raw_pages.splitlines() if l.strip())
            STOP = {"abstract","introduction","arxiv","received","accepted","published online"}
            ignored_kw = {"copyright","doi:","journal of","proceedings of","vol.","no.","issn","isbn"}
            good_lines = []
            for ln in raw.splitlines()[:1000]:
                low = ln.lower()
                if len(ln) < 15: continue
                if re.match(r"^[\d][\d\s\.:]*$", low): continue
                if any(low.startswith(s) for s in STOP): continue
                if any(g in low for g in ignored_kw): continue
                good_lines.append(ln)

            # 拼标题 span（前15个好行）
            title_span = ""
            for i, line in enumerate(good_lines[:15]):
                span = line
                for j in range(i+1, min(i+4, len(good_lines))):
                    nxt = good_lines[j]
                    if nxt is not line:
                        span += " " + nxt
                if len(span) > 200:
                    break
                if len(span) >= 15:
                    title_span = span
                    break
            if not title_span:
                title_span = r.path.stem.replace("_"," ").replace("-"," ")

            first_500 = raw[:500]

            # ── 三路全局扫描（全量543行报告） ──────────────────
            RELEVANT_FIELDS = ["标题", "摘要"]
            best_overall = 0.0
            best_row_idx = -1
            best_method_label = ""

            for ri, row in enumerate(report_rows):
                row_texts = {f: row.get(f,"") for f in RELEVANT_FIELDS if row.get(f,"")}

                # M1: title_span vs 报告标题
                for f, txt in row_texts.items():
                    s = fuzzy_score(title_span, txt)
                    if s > best_overall:
                        best_overall, best_row_idx, best_method_label = s, ri, f"span→{f}"

                # M2: first_500 vs 报告标题（降权，长文本稀释）
                for f, txt in row_texts.items():
                    s = fuzzy_score(first_500, txt) * 0.8
                    if s > best_overall:
                        best_overall, best_row_idx, best_method_label = s, ri, f"p500→{f}"

                # M3: 文件名 vs 报告标题
                fname_norm = r.path.stem.replace("_"," ").replace("-"," ")
                for f, txt in row_texts.items():
                    s = fuzzy_score(fname_norm, txt)
                    if s > best_overall:
                        best_overall, best_row_idx, best_method_label = s, ri, f"fname→{f}"

            r.extracted_title = title_span
            best_s = best_overall
            best_i = best_row_idx
            r.match_method = best_method_label

            if best_s >= MATCH_THRESHOLD:
                # 按报告标准标题重命名
                std_title = report_rows[best_i]["标题"]
                new_name = re.sub(r"[^A-Za-z0-9]+", "_", std_title.lower()).strip("_")[:80] + ".pdf"
                # 尝试保留 arxiv_id
                m = re.search(r"(\d{4}\.\d{4,5})", r.path.name)
                if m:
                    new_name = f"{m.group(1)}_{new_name}"
                dest = r.path.parent / new_name
                already = dest.resolve() == r.path.resolve()
                if not dry and not already:
                    r.path.rename(dest)
                r.filename_kind = "matched"
                renamed += 1
            else:
                # 移到非相关文件夹
                dest = low_dir / r.path.name
                if not dry:
                    low_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(r.path), str(dest))
                r.filename_kind = "unmatched"
                moved_low += 1

    # ── 统计 PHD-Buyya 根目录剩余 PDF 数 ────────────────────
    remaining_top = len(list(pdf_root.glob("*.pdf")))

    # ── 报告 ──────────────────────────────────────────────────
    print(f"\n[done]")
    print(f"  renamed (matched)   : {renamed}")
    print(f"  moved → thesis_review : {moved_thesis}")
    print(f"  moved → batch5        : {moved_batch5}")
    print(f"  moved → {LOW_RELEV_ALL} : {moved_low}")
    if dry:
        print("  (dry-run — 未修改任何文件)")
    print(f"  PHD-Buyya 根目录剩余 PDF: {remaining_top}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
