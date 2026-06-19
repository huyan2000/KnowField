#!/usr/bin/env python3
"""本地报告重建：扫本地 PDF、enrich、合并为 paper_search_report.{html,csv}。

不联网，不爬 arXiv，不调 S2 —— 完全基于现有 CSV 和本地 PDF。
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build the single unified paper report.")
    parser.add_argument(
        "--keep-intermediates",
        action="store_true",
        help="Keep intermediate JSONL/CSV files instead of deleting them.",
    )
    parser.add_argument(
        "--rename-scope",
        choices=["all", "arxiv"],
        default="all",
        help="重命名作用范围。all = 整个本地 PDF 根目录（默认）；arxiv = 只处理 arxiv_latest_papers/。",
    )
    parser.add_argument(
        "--no-dedup",
        action="store_true",
        help="跳过报告生成后的 PDF slug 去重。",
    )
    parser.add_argument(
        "--no-rename",
        action="store_true",
        help="跳过报告生成后的 PDF 重命名。",
    )
    parser.add_argument(
        "--dry-run-rename",
        action="store_true",
        help="重命名步骤只预览，不实际改动文件。",
    )
    parser.add_argument(
        "--no-multipaper",
        action="store_true",
        help="跳过合订本/多论文反向匹配（默认开启）。",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    base = PACKAGE_ROOT

    from utils.reconcile import reconcile_local_pdfs
    from utils.paths import find_pdf_root
    from reporting.enrichment import build as build_enriched
    from reporting.missing import main as build_missing_downloads_report
    from reporting.unified import build as build_unified
    from crawlers.s2 import bootstrap_intermediates_from_unified
    from pdf_ops.dedup import dedup_pdfs
    from pdf_ops.rename import main as rename_pdfs

    bootstrap_intermediates_from_unified(base)

    print("[1/5] Reconciling local PDFs …")
    reconcile_local_pdfs(write_reports=False, enable_multipaper=not args.no_multipaper)

    print("[2/5] Enriching downloadable CSV …")
    enriched_args = SimpleNamespace(
        input=str(base / "papers_search_results_downloadable.csv"),
        output=str(base / "papers_search_results.html"),
        output_csv=str(base / "papers_search_results_downloadable.csv"),
    )
    build_enriched(enriched_args)

    print("[3/5] Building unified report …")
    _old_argv = sys.argv[:]
    try:
        sys.argv = [
            "build_missing_downloads_report",
            "--input", str(base / "papers_search_results_downloadable.csv"),
            "--output", str(base / "papers_missing_downloads.html"),
            "--output-csv", str(base / "papers_missing_downloads.csv"),
            "--no-scan-local",
        ]
        build_missing_downloads_report()
    finally:
        sys.argv = _old_argv

    html_path, csv_path, row_count = build_unified(base)
    print(f"  → {html_path.name}  ({html_path.stat().st_size // 1024} KB)")
    print(f"  → {csv_path.name}  ({csv_path.stat().st_size // 1024} KB, {row_count} rows)")

    if args.no_rename:
        print("[4/5] PDF 重命名：已跳过 (--no-rename)")
    else:
        scope = args.rename_scope
        print(f"[4/5] 按报告标题重命名 PDF (scope={scope}) …")
        rename_argv = ["--scope", scope]
        if args.dry_run_rename:
            rename_argv.append("--dry-run")
        try:
            rename_pdfs(rename_argv)
        except SystemExit:
            pass
        except Exception as exc:
            print(f"[警告] 重命名失败：{exc}")

    if args.no_dedup:
        print("[5/5] PDF 去重：已跳过 (--no-dedup)")
    else:
        print("[5/5] PDF 去重 …")
        try:
            pdf_root = find_pdf_root(base.parent)
            dup_stats = dedup_pdfs(pdf_root, dry_run=False)
            if dup_stats["dup_groups"]:
                print(f"  → 删除 {dup_stats['deleted']} 个副本（{dup_stats['dup_groups']} 组），"
                      f"剩余 {dup_stats['total_after']} 个 PDF")
            else:
                print(f"  → 无重复，本地共 {dup_stats['total_after']} 个 PDF")
        except Exception as exc:
            print(f"[警告] 去重失败：{exc}")

    if not args.keep_intermediates:
        intermediates = [
            base / "papers_search_results.html",
            base / "papers_search_results_downloadable.csv",
            base / "papers_missing_downloads.html",
            base / "papers_missing_downloads.csv",
            base / "arxiv_latest_half_year.csv",
            base / "arxiv_latest_half_year.html",
            base / "local_pdf_reconciliation.html",
            base / "local_pdfs_not_in_search.html",
            base / "local_pdfs_not_in_search.csv",
            base / "papers_search_results.csv",
            base / "pdf_rename_audit.csv",
        ]
        removed = [p.name for p in intermediates if p.exists() and (p.unlink(missing_ok=True) or True)]
        if removed:
            print(f"  [cleanup] removed {len(removed)} intermediate file(s): {', '.join(removed)}")

    print("\nDone.")


if __name__ == "__main__":
    run()
