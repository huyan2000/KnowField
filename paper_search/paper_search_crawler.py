#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""爬虫入口：S2 + arXiv 抓取，自动重命名 / 去重 / 出报告。

执行：
    python3 paper_search_crawler.py                # 完整流程
    python3 paper_search_crawler.py --reports-only --skip-arxiv  # 只重出报告
    python3 paper_search_crawler.py --help
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from crawlers.s2 import main


if __name__ == "__main__":
    print("正在启动论文搜索/报告流程...", flush=True)
    try:
        main()
    except Exception as exc:
        print(f"\n错误: {exc}", flush=True)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    print("\n完成。", flush=True)
