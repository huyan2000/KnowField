#!/usr/bin/env python3
"""本地报告入口：扫本地 PDF + 现有 CSV → paper_search_report.{html,csv}。

不联网，不爬 arXiv。

    python3 build_final_report.py                    # 默认: 全 PDF 根目录重命名 + 去重
    python3 build_final_report.py --rename-scope arxiv     # 只重命名 arxiv_latest_papers/
    python3 build_final_report.py --no-rename --no-dedup   # 只重出报告
    python3 build_final_report.py --dry-run-rename   # 预览重命名计划
    python3 build_final_report.py --help
"""
from __future__ import annotations

from reporting.build_final import run


if __name__ == "__main__":
    run()
