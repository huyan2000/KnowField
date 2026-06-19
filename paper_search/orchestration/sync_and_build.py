#!/usr/bin/env python3
"""
├─ 报告生成后自动清理所有中间 CSV/HTML，只保留
│  paper_search_report.html
│  paper_search_report.csv
└─ 用法同上
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import sys
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

# ── 路径 ──────────────────────────────────────────────────────────────────
from utils.paths import find_pdf_root

# ── 配置 ──────────────────────────────────────────────────────────────────
DOWNLOADABLE_CSV = "papers_search_results_downloadable.csv"
DEFAULT_MAIN_CSV  = "papers_search_results.csv"

# 可下载 CSV 的规范字段顺序（固定，不因各行 key 变化而改变）
STD_FIELDNAMES = [
    "序号",
    "标题",
    "作者",
    "年份",
    "出处",
    "引用数",
    "评分",
    "轨道",
    "领域",
    "核心目标",
    "是否顶会顶刊",
    "摘要",
    "下载状态",
    "下载说明",
    "内容已检测",
    "本地PDF",
    "PDF直链",
    "正确论文页",
    "链接修正说明",
    "原始链接",
    "DOI",
    "OA状态",
]

# 匹配阈值：SequenceMatcher ratio ≥ 此值视为同一篇
MATCH_THRESHOLD = 0.745

# ── PDF 内容提取：首屏过滤行 & 假元数据标题检测 ──────────────────
# 对 header/legal 行中更通用的过滤关键词（既不是摘要/引言，也不是作者/机构）
STOP_LINES = {
    "abstract", "introduction", "arxiv", "ieee transactions",
    "ieee internet of things journal", "ieee transactions on mobile computing",
    "received", "accepted", "published online",
    "proceedings", "this paper is included", "open access to the",
    "sponsored by", "isbn", "license",
}

# 作者/机构行关键词，标题跨行读到这行就停止
_AUTHOR_STOP = {
    "@", "email", "institute", "university", "department", "laboratory",
    "inc.", "corp", "google", "facebook", "microsoft", "ibm", " amazon",
    "et al.", "et al", "doi:", "http://", "https://", "www.",
}

# Word/模板生成的假标题特征：如 "Word-processor-exported manuscript file"
_FAKE_TITLE_RE = re.compile(
    r'(?i)^microsoft\s+(word|office)|\.docx?\)?$|final[\s_-]?article',
)

# ── 经典必读论文 ─────────────────────────────────────────────────────────────
# 当主爬虫 CSV 未包含某篇经典论文时，由 sync_and_build.py 自动补全。
CLASSIC_PAPERS = [
    {
        "序号": "",
        "标题": "Communication-Efficient Learning of Deep Networks from Decentralized Data",
        "作者": "H. Brendan McMahan; Eider Moore; Daniel Ramage; Seth Hampson; Blaise Aguera y Arcas",
        "年份": "2017",
        "出处": "AISTATS",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G1, G4",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：FedAvg 基础论文，定义了现代联邦学习的基本训练范式。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://proceedings.mlr.press/v54/mcmahan17a.html",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Towards Federated Learning at Scale: System Design",
        "作者": "Keith Bonawitz; Hubert Eichner; Wolfgang Grieskamp; Dzmitry Huba; Alex Ingerman",
        "年份": "2019",
        "出处": "MLSys",
        "引用数": "",
        "评分": "99",
        "轨道": "B1 (FL系统实现)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：大规模 FL 系统设计论文。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://proceedings.mlsys.org/paper_files/paper/2019/hash/bd686fd640be98efaae0091fa301e613-Abstract.html",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Federated Optimization in Heterogeneous Networks",
        "作者": "Tian Li; Anit Kumar Sahu; Manzil Zaheer; Maziar Sanjabi; Ameet Talwalkar; Virginia Smith",
        "年份": "2020",
        "出处": "MLSys",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G1, G4",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：FedProx，异构 FL 聚合基线。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://proceedings.mlsys.org/paper_files/paper/2020/hash/1f5fe83998a09396ebe6477d9475ba0c-Abstract.html",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "SCAFFOLD: Stochastic Controlled Averaging for Federated Learning",
        "作者": "Sai Praneeth Karimireddy; Satyen Kale; Mehryar Mohri; Sashank Reddi; Sebastian Stich; Ananda Theertha Suresh",
        "年份": "2020",
        "出处": "ICML",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G1, G2",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：用 control variates 处理 client drift。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://proceedings.mlr.press/v119/karimireddy20a.html",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "FedScale: Benchmarking Model and System Performance of Federated Learning at Scale",
        "作者": "Fan Lai; Yinwei Dai; Sanjay Sri Vallabh Singapuram; Jiachen Liu; Xiangfeng Zhu; H. Madhyastha; Mosharaf Chowdhury",
        "年份": "2022",
        "出处": "ICML",
        "引用数": "",
        "评分": "99",
        "轨道": "B1 (FL系统实现)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：大规模 FL benchmark / runtime。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://proceedings.mlr.press/v162/lai22a.html",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Federated Learning on Non-IID Features via Local Batch Normalization",
        "作者": "Xiaoxiao Li; Meirui Jiang; Xiaofei Zhang; Michael Kamp; Qi Dou",
        "年份": "2021",
        "出处": "ICLR",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G3",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：FedBN，处理 feature shift 的个性化 FL 基线。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://openreview.net/forum?id=6YEQUn0QICG",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Personalized Federated Learning with Moreau Envelopes",
        "作者": "Canh T. Dinh; Nguyen H. Tran; Tuan Dung Nguyen",
        "年份": "2020",
        "出处": "NeurIPS",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G3",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：pFedMe，个性化 FL 经典方法。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://proceedings.neurips.cc/paper/2020/hash/f4f1f13c8289ac1b1ee0ff176b56fc60-Abstract.html",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Ditto: Fair and Robust Federated Learning Through Personalization",
        "作者": "Tian Li; Shengyuan Hu; Ahmad Beirami; Virginia Smith",
        "年份": "2021",
        "出处": "ICML",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G3",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：个性化、鲁棒性和公平性的代表性工作。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://proceedings.mlr.press/v139/li21h.html",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Practical Secure Aggregation for Privacy-Preserving Machine Learning",
        "作者": "Keith Bonawitz; Vladimir Ivanov; Ben Kreuter; Antonio Marcedone; H. Brendan McMahan",
        "年份": "2017",
        "出处": "CCS",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G1, G4",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：安全聚合基础论文。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://dl.acm.org/doi/10.1145/3133956.3133982",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Oort: Efficient Federated Learning via Guided Participant Selection",
        "作者": "Fan Lai; et al.",
        "年份": "2021",
        "出处": "OSDI",
        "引用数": "",
        "评分": "99",
        "轨道": "B1 (FL系统实现)",
        "领域": "",
        "核心目标": "G1, G4",
        "是否顶会顶刊": "是",
        "摘要": "经典必读：系统效用驱动的客户端选择。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://www.usenix.org/conference/osdi21/presentation/lai",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "An Architectural Blueprint for Autonomic Computing",
        "作者": "Autonomic Computing Working Group",
        "年份": "2006",
        "出处": "White Paper",
        "引用数": "",
        "评分": "99",
        "轨道": "B3 (自治/自适应系统)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "否",
        "摘要": "经典必读：MAPE-K / autonomic computing 基础材料。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://www-03.ibm.com/autonomic/pdfs/AC%20Blueprint%20White%20Paper%20V7.pdf",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Rainbow: Architecture-Based Self-Adaptation with Reusable Infrastructure",
        "作者": "David Garlan; Shang-Wen Cheng; An-Cheng Huang; Bradley Schmerl; Peter Steenkiste",
        "年份": "2004",
        "出处": "IEEE Computer",
        "引用数": "",
        "评分": "99",
        "轨道": "B3 (自治/自适应系统)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "否",
        "摘要": "经典必读：self-adaptive systems 代表性框架。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://www.cs.cmu.edu/~garlan/publications/RainbowComputer04.pdf",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "A survey of autonomic computing—degrees, models, and applications",
        "作者": "M. Huebscher; J. McCann",
        "年份": "2008",
        "出处": "ACM Computing Surveys",
        "引用数": "",
        "评分": "99",
        "轨道": "B3 (自治/自适应系统)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "否",
        "摘要": "经典必读：autonomic computing 综述。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://www.semanticscholar.org/paper/0decbb8696f2b5025977ffce3c03ce7108097fd4",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Software Engineering for Self-Adaptive Systems: A Research Roadmap",
        "作者": "B. Cheng; R. de Lemos; H. Giese; P. Inverardi; J. Magee; J. Andersson",
        "年份": "2009",
        "出处": "Software Engineering for Self-Adaptive Systems",
        "引用数": "",
        "评分": "99",
        "轨道": "B3 (自治/自适应系统)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "否",
        "摘要": "经典必读：self-adaptive systems 研究路线图。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://www.semanticscholar.org/paper/5c7e1b47e0864c8e9e075389d17c31352b0484ee",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Engineering Self-Adaptive Systems through Feedback Loops",
        "作者": "Yuriy Brun; Giovanna Di Marzo Serugendo; Cristina Gacek; Holger Giese; Holger Kienle; Marin Litoiu",
        "年份": "2009",
        "出处": "Software Engineering for Self-Adaptive Systems",
        "引用数": "",
        "评分": "99",
        "轨道": "B3 (自治/自适应系统)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "否",
        "摘要": "经典必读：反馈环视角的自治系统基础论文。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://www.semanticscholar.org/paper/3c111e31a8a971982520adf51945a402d13ce4da",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "Self-adaptive systems: A survey of current approaches, research challenges and applications",
        "作者": "Frank D. Macias-Escriva; R. Haber; Raul M. del Toro; Vicente Hernandez",
        "年份": "2013",
        "出处": "Expert Systems with Applications",
        "引用数": "",
        "评分": "99",
        "轨道": "B3 (自治/自适应系统)",
        "领域": "",
        "核心目标": "G4",
        "是否顶会顶刊": "否",
        "摘要": "经典必读：self-adaptive systems 综述。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://www.semanticscholar.org/paper/8646740a86c65a531c571fe312f8e3189032672c",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
    {
        "序号": "",
        "标题": "A Survey on Concept Drift Adaptation",
        "作者": "Jie Lu; Anjin Liu; Fan Dong; Feng Gu; Joao Gama; Guangquan Zhang",
        "年份": "2018",
        "出处": "ACM Computing Surveys",
        "引用数": "",
        "评分": "99",
        "轨道": "A (FL算法)",
        "领域": "",
        "核心目标": "G2",
        "是否顶会顶刊": "否",
        "摘要": "经典必读：概念漂移综述。",
        "下载状态": "missing",
        "下载说明": "本地未下载",
        "内容已检测": "",
        "本地PDF": "",
        "PDF直链": "",
        "正确论文页": "https://dl.acm.org/doi/10.1145/3190525",
        "链接修正说明": "经典必读种子",
        "原始链接": "",
        "DOI": "",
        "OA状态": "",
    },
]


# ══════════════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class LocalPdf:
    path: Path
    source: str
    title: str
    norm: str
    extracted_title: str = ""          # PDF 元数据提取的完整标题（可能不同于文件名启发式）
    matched_index: Optional[int] = None
    matched_title: str = ""
    match_score: float = 0.0
    content_checked: bool = False


# ══════════════════════════════════════════════════════════════════════════
# 工具函数
# ══════════════════════════════════════════════════════════════════════════

def normalize(text: str) -> str:
    text = (text or "").lower()
    text = text.replace("–", "-").replace("—", "-").replace("−", "-")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def norm_title(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def extract_title(path: Path) -> tuple[str, str, bool]:
    """从 PDF 第一页提取标题，元数据仅作参考。返回 (title, meta_full_title, content_checked)。"""
    raw = path.stem
    raw = re.sub(r"^\d{8}_", "", raw)
    raw = re.sub(r"^\d{3}_\d{4}_\d{2}_", "", raw)
    title = raw.replace("_", " ").strip() if len(raw) > 5 else ""
    meta_full_title = ""
    content_checked = False

    try:
        from pypdf import PdfReader  # type: ignore
        reader = PdfReader(str(path))

        # 第一优先：从 PDF 第一页提取标题（作者行之前的最后一段非机构文字）
        first_page = reader.pages[0].extract_text() or ""
        all_lines = [l.strip() for l in first_page.splitlines()]
        title_lines: list[str] = []   # shared by both branches below

        # Step 1 — 找到作者/机构行的起始索引
        def _is_authorish(lx: str) -> bool:
            low = lx.lower()

            # Proceedings header — never author
            if re.search(
                r'this paper is included|open access to the pro'
                r'|sponsored by|isbn|published in the pro',
                low,
            ):
                return False

            if not lx or len(lx) < 4:
                return False
            if re.search(r"\b(et al\.?)\b", low):
                return True
            if "@" in lx:
                return True
            if re.search(r"\b(email|corresponding)\b", low):
                return True
            if re.search(r"\b(university|department|institute|school|center|college|"
                         r"laboratory|faculty|inc\.?|corp\.?|llc|company)\b", low):
                return True
            if re.search(r"\b(computer|science|engineering)\b", low) and re.search(r"\b[A-Z][a-z]{2,}\b", lx):
                return True
            # "M. Usman Iftikhar" / "S. Izadi, M. Ahmadi"
            if re.search(r"\b[A-Z]\.\s*[A-Z]", lx):
                return True
            if re.search(r"[A-Z][a-z]+,\s*[A-Z]", lx):
                return True
            # Short line with ≥3 独立首字母大写词 或 恰好 2 个大写名字词（"Jianyu Wang"）
            caps = set(re.findall(r"\b[A-Z][a-z]{1,3}\b", lx))
            if len(caps) >= 3 and len(lx) < 120:
                return True
            # Two-caps tokens matching a name pattern — exclude title-form sentences and short words
            _TITLE_AND_FORM = {
                "design", "implementation", "system", "systems", "methods", "method",
                "approach", "framework", "algorithm", "paper", "proceedings",
                "conference", "workshop", "journal", "transaction", "symposium",
                "volume", "issue", "chapter", "edition", "results", "analysis",
                "evaluation", "experimental",
            }
            _SKIP_LOW = {
                "and", "or", "of", "in", "the", "for", "with",
                "on", "at", "to", "by", "vs", "as", "an", "is",
            }
            _all_caps = set(re.findall(r"[A-Z][a-z]{2,}", lx))
            name_cands = {
                w for w in _all_caps
                if w.lower() not in _SKIP_LOW and w.lower() not in _TITLE_AND_FORM
            }
            if len(name_cands) == 2 and len(lx) < 55:
                return True
            return False

        author_idx: Optional[int] = None
        for i, ln in enumerate(all_lines):
            if _is_authorish(ln):
                author_idx = i
                break

        if author_idx is not None:
            # Step 2 — 从作者行前一行向前扫描，跳过机构/页眉，收集标题段
            INSTITUTION_HEADERS = {
                "university", "department", "institute", "school", "center",
                "laboratory", "faculty", "college", "inc", "corp", "llc", "company",
                "computer science", "engineering",
            }
            _instit_re = re.compile(
                r'\b(?:' + '|'.join(re.escape(k) for k in INSTITUTION_HEADERS) + r')\b'
            )
            STOP_STARTS = {
                "this paper is included", "open access", "sponsored by",
                "copyright", "all rights reserved", "isbn", "license",
            }

            # 跳过作者行本身

            # 向前逐行，遇到机构/页眉行停止，其它作为标题行
            for j in range(author_idx - 1, -1, -1):
                ln = all_lines[j]
                low = ln.lower()

                if not ln or len(ln) < 4:
                    break
                if re.fullmatch(r"\d{4}", ln) or re.search(r"\s+(19\d{2}|20\d{2})\s*$", ln):
                    break
                if any(kw in low for kw in STOP_LINES):
                    break
                if any(kw in low for kw in STOP_STARTS):
                    break
                if _instit_re.search(low):
                    break

                # 可能是标题行（有标点或大小写）
                title_lines.insert(0, ln)

            if title_lines:
                title = " ".join(title_lines)
        else:
            # 没有检测到作者行 — 退化为原来的第一条非停用词行逻辑
            for line in all_lines:
                line = line.strip()
                low = line.lower()
                if not line or len(line) < 4:
                    continue
                if any(kw in low for kw in STOP_LINES):
                    break
                if re.fullmatch(r"\d{4}", line) or re.search(r"\s+(19\d{2}|20\d{2})\s*$", line):
                    continue
                # Author / institutional stop
                if _is_authorish(line):
                    break
                title_lines.insert(0, line)
                break  # 取第一条

        if title_lines and not title:
            title = " ".join(title_lines)

        # 第二参考：读取元数据（仅用于差异对比，不改变 title）
        meta = reader.metadata
        if meta:
            raw_title = meta.get("/Title") or meta.get("Title") or ""
            if isinstance(raw_title, str) and not _FAKE_TITLE_RE.search(raw_title):
                meta_title = raw_title.strip()
                if meta_title and meta_title != title and len(meta_title) > 10:
                    meta_full_title = meta_title
        content_checked = True

    except Exception:
        pass

    if not title:
        title = raw
    return title, meta_full_title, content_checked


def pdf_priority(path: Path, root: Path) -> tuple[int, str]:
    try:
        rel = path.resolve().relative_to(root.resolve())
        depth = len(rel.parts)
    except Exception:
        depth = 999
    return (depth, str(path))


def rel_to_report(path: Path, report_dir: Path) -> str:
    try:
        return os.path.relpath(path.resolve(), report_dir.resolve())
    except Exception:
        return str(path)


# ══════════════════════════════════════════════════════════════════════════
# PDF 扫描与匹配
# ══════════════════════════════════════════════════════════════════════════

def scan_local_pdfs(pdf_root: Path) -> list[LocalPdf]:
    """扫描 PHD-Buyya 目录，返回所有 PDF 的元数据列表。"""
    if not pdf_root.exists():
        print(f"  [警告] PDF 根目录不存在：{pdf_root}")
        return []
    pdfs = list(pdf_root.rglob("*.pdf"))
    out: list[LocalPdf] = []
    for path in sorted(pdfs):
        title, meta_title, checked = extract_title(path)
        source = path.parent.name if path.parent != pdf_root else "root"
        out.append(LocalPdf(
            path=path,
            source=source,
            title=title,
            norm=normalize(title),
            extracted_title=meta_title,
            content_checked=checked,
        ))
    return out


# ══════════════════════════════════════════════════════════════════════════
# 文件名安全化
# ══════════════════════════════════════════════════════════════════════════

_ILLEGAL_CHARS = re.compile(r'[\\/:*?"<>|\x00-\x1f]')   # 绝对禁用的字符
MAX_FILENAME_LEN = 100  # macOS APFS 支持 255，100 足够且提示性长


def make_safe_filename(title: str) -> str:
    """将论文标题转为安全的文件名（不含扩展名），词之间用 + 连接。
    适用场景：生成通用兼容名；不要用于重命名以已有文件名，避免循环。"""
    name = title.strip().rstrip(". ")
    if not name:
        return "untitled"
    name = _ILLEGAL_CHARS.sub("_", name)
    # 首有空格时合并为 +，无空格时独词（如 'Communication-Efﬁcient Learning' 含空格）→ + 连接
    if " " in name:
        name = re.sub(r"[ _]+", "+", name).strip("+")
    if len(name) > MAX_FILENAME_LEN:
        name = name[:MAX_FILENAME_LEN].rstrip(". ")
    return name or "untitled"


def make_readable_filename(title: str) -> str:
    """从论文标题生成 *可读*的文件名（不含扩展名）。
    行为：
    1) 展开所有 + 为空格（覆盖从 +-joined 文件名反向推导的情况）；
    2) 移除首尾空白和尾部句号/空格（Windows 规则）；
    3) 仅替换 *真正非法* 的字符为 `_`（空格、横杠 `-`、逗号 `,`、冒号 `:`、
       括号 `()`、撇号 `'`、句点 `.` 均保留，以贴近论文标题原貌）；
    4) 标题过长则截断（保留缩略形式的可读性）；
    5) 置换后的文件可直接被 read 打开，也可在 Finder 中舒适阅读。
    """
    # Step 1 – 展开 + 为空格（对从 +-joined 文件名回退的情况尤其重要）
    name = title.replace("+", " ")
    # Step 2 – strip
    name = name.strip().rstrip(". ")
    if not name:
        return "untitled"
    # Step 3 – 只替换绝对非法字符；空格以及 - , : ( ) ' . 全部保留
    name = _ILLEGAL_CHARS.sub("_", name)
    # 处理连续空格
    name = re.sub(r" {2,}", " ", name)
    # Step 4 – 截断，尽量在句子边界处的空格截断
    if len(name) > MAX_FILENAME_LEN:
        cut = name.rfind(" ", 0, MAX_FILENAME_LEN)
        if cut < 40:          # 词太短，硬截更均匀
            cut = MAX_FILENAME_LEN
        name = name[:cut].rstrip()
    return name or "untitled"


def rename_pdfs_by_title(
    local_pdfs: list[LocalPdf],
    *,
    root: Path,
    dry_run: bool = False,
) -> tuple[int, list[str]]:
    """用 PDF 元数据提取的标题重命名 PHD-Buyya 中的文件。

    目标格式：`<论文标题>.pdf`
    返回 (已改名数量, 日志列表)。
    """
    renamed: list[str] = []
    used_names: dict[str, int] = {}   # base_name → 已使用次数（用于去重后缀）
    errors: list[str] = []

    for pdf in local_pdfs:
        src = pdf.path
        # 优先用元数据完整标题，回退到启发式标题
        raw_title = pdf.extracted_title or pdf.title
        # make_readable_filename 保留空格和标题原貌，使之与当前 + 文件名不同，从而触发重命名
        base = make_readable_filename(raw_title)
        if base == "untitled":
            continue

        # 去重处理
        used_names[base] = used_names.get(base, 0) + 1
        suffix = "" if used_names[base] == 1 else f"_{used_names[base]}"
        new_name = f"{base}{suffix}.pdf"
        dst = src.parent / new_name

        if src == dst:
            continue  # 文件名相同，跳过
        if dst.exists():
            errors.append(f"  目标已存在，跳过：{new_name}")
            continue
        if dry_run:
            renamed.append(f"[预览] {src.name} → {new_name}")
        else:
            try:
                src.rename(dst)
                renamed.append(f"[已改名] {src.name} → {new_name}")
                # 更新 LocalPdf.path 指向新路径
                pdf.path = dst
            except OSError as e:
                errors.append(f"  改名失败：{src.name} → {new_name}  ({e})")

    return len(renamed), renamed + errors


def bootstrap_from_report(report_csv: Path, dl_csv: Path) -> None:
    """从最终报告 CSV 重建下载中间表，默认保留现有下载状态和本地 PDF 字段。"""
    report_rows = read_csv(report_csv)
    if not report_rows:
        return

    dl_fields = STD_FIELDNAMES  # 直接使用规范字段顺序，避免依赖 CLASSIC 模板
    out: list[dict[str, str]] = []
    for idx, r in enumerate(report_rows, start=1):
        row: dict[str, str] = {k: "" for k in dl_fields}
        row["序号"]         = str(idx)
        # 优先填充来源报告中的值（兼容新旧字段名称）
        row["标题"]       = r.get("标题", "")
        row["作者"]       = r.get("作者", "")
        row["年份"]       = r.get("年份", "")
        row["出处"]       = r.get("出处", "") or r.get("出处或类别", "")
        row["评分"]       = r.get("评分", "")
        row["轨道"]       = r.get("轨道", "")
        row["领域"]       = r.get("领域", "")
        row["核心目标"]   = r.get("核心目标", "")
        top_venue       = r.get("是否顶会顶刊", "")
        row["是否顶会顶刊"] = "是" if top_venue == "是" else top_venue
        row["摘要"]       = r.get("摘要", "")
        # 保留现有下载状态和本地 PDF（可能来自之前的 sync）
        row["下载状态"]   = r.get("下载状态", "missing")
        row["下载说明"]   = status_note(row["下载状态"])
        row["内容已检测"] = r.get("内容已检测", "")
        row["本地PDF"]    = r.get("本地PDF", "")
        row["PDF直链"]    = r.get("PDF直链", "")
        row["正确论文页"] = r.get("正确论文页", "") or r.get("论文页", "")
        row["链接修正说明"] = "从最终报告重建"
        row["原始链接"]   = ""
        row["DOI"]        = r.get("DOI", "")
        row["OA状态"]     = ""
        out.append(row)

    with dl_csv.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=dl_fields)
        writer.writeheader()
        writer.writerows(out)
    print(f"  ✓ 从报告 CSV 重建了下载中间表：{dl_csv.name}（{len(out)} 行）")


def status_note(status: str) -> str:
    notes = {
        "downloaded": "已下载到本地",
        "exists": "本地已有PDF",
        "open_pdf_available": "有公开PDF链接，尚未本地保存",
        "missing": "本地未下载",
    }
    return notes.get(status, status or "本地未下载")


def match_pdfs_to_rows(local_pdfs: list[LocalPdf], rows: list[dict[str, str]]) -> None:
    """将本地 PDF 列表与 CSV 行做模糊匹配，就地更新「本地PDF」字段。"""
    row_norms = [(i, norm_title(r.get("标题", "")), r) for i, r in enumerate(rows)]
    row_norms.sort(key=lambda x: -len(x[1]))   # 长标题优先

    used_pdf_indices: set[int] = set()

    for row_idx, row_norm, row in row_norms:
        if not row_norm:
            continue
        best_pdf_idx: Optional[int] = None
        best_score: float = 0.0

        for pdf_idx, pdf in enumerate(local_pdfs):
            if pdf_idx in used_pdf_indices:
                continue
            score = SequenceMatcher(None, row_norm, pdf.norm).ratio()
            if score >= MATCH_THRESHOLD and score > best_score:
                best_score = score
                best_pdf_idx = pdf_idx

        if best_pdf_idx is not None:
            pdf = local_pdfs[best_pdf_idx]
            used_pdf_indices.add(best_pdf_idx)
            row["本地PDF"] = str(pdf.path.resolve())
            row["_match_score"] = str(round(best_score, 4))
            row["_match_method"] = "fuzzy_title"
            pdf.matched_index = row_idx
            pdf.matched_title = row.get("标题", "")
            pdf.match_score = best_score


# ══════════════════════════════════════════════════════════════════════════
# 经典论文补全
# ══════════════════════════════════════════════════════════════════════════

def inject_missing_classics(rows: list[dict[str, str]], local_pdfs: list[LocalPdf]) -> int:
    """把 CLASSIC_PAPERS 中还没出现在 rows 里的论文追加进去，并尝试匹配本地 PDF。"""
    existing_titles = {norm_title(r.get("标题", "")) for r in rows}
    added = 0
    unused_pdfs = [p for p in local_pdfs if p.matched_index is None]

    for classic in CLASSIC_PAPERS:
        ctitle_norm = norm_title(classic["标题"])
        if ctitle_norm in existing_titles:
            continue

        # 以所有 fieldnames 为蓝本，填经典论文数据
        row: dict[str, str] = {k: "" for k in CLASSIC_PAPERS[0]}
        row.update(classic)

        # 常规字段与标题等填入
        row["标题"]       = classic["标题"]
        row["作者"]       = classic["作者"]
        row["年份"]       = classic["年份"]
        row["出处"]       = classic["出处"]
        row["评分"]       = classic.get("评分", "99")
        row["轨道"]       = classic.get("轨道", "A (FL算法)")
        row["核心目标"]   = classic.get("核心目标", "")
        row["是否顶会顶刊"] = classic.get("是否顶会顶刊", "是")
        row["摘要"]       = classic.get("摘要", "")
        row["下载状态"]   = "missing"
        row["链接修正说明"] = classic.get("链接修正说明", "经典必读种子")

        # 尝试匹配本地 PDF
        best_pdf: Optional[LocalPdf] = None
        best_score: float = 0.0
        for pdf in unused_pdfs:
            score = SequenceMatcher(None, ctitle_norm, pdf.norm).ratio()
            if score >= MATCH_THRESHOLD and score > best_score:
                best_score = score
                best_pdf = pdf
        if best_pdf is not None:
            row["本地PDF"] = str(best_pdf.path.resolve())
            row["下载状态"] = "exists"
            best_pdf.matched_index = len(rows)   # 临时标记
            best_pdf.matched_title = row["标题"]
            best_pdf.match_score = best_score

        rows.append(row)
        existing_titles.add(ctitle_norm)
        added += 1

    return added


# ══════════════════════════════════════════════════════════════════════════
# CSV 读写
# ══════════════════════════════════════════════════════════════════════════

def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def dedup_match_fields(rows: list[dict[str, str]]) -> None:
    """内部匹配辅助字段不用写入 CSV，就地清理。"""
    for row in rows:
        row.pop("_match_score", None)
        row.pop("_match_method", None)


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    # 先清理内部匹配字段
    dedup_match_fields(rows)
    fieldnames = STD_FIELDNAMES
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ══════════════════════════════════════════════════════════════════════════
# 下载状态更新
# ══════════════════════════════════════════════════════════════════════════

def update_download_status(rows: list[dict[str, str]], base: Path) -> None:
    """根据本地PDF字段更新每行的下载状态。无效路径（不存在或太小）会被置空。"""
    for row in rows:
        local_pdf_val = row.get("本地PDF", "").strip()
        if local_pdf_val:
            p = Path(local_pdf_val)
            if not p.is_absolute():
                p = base / p
            try:
                exists_and_valid = p.exists() and p.stat().st_size > 10_000
            except OSError:
                exists_and_valid = False
            row["下载状态"] = "exists" if exists_and_valid else "missing"
            if not exists_and_valid:
                # 清除无效/空文件路径，避免 HTML 中出现死链
                row["本地PDF"] = ""
        elif not row.get("下载状态", "").strip():
            row["下载状态"] = "missing"


# ══════════════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════════════

def sync_and_build(
    base: Optional[Path] = None,
    *,
    run_build: bool = True,
    print_unmatched: bool = True,
    rename_pdfs: bool = True,
    dry_run: bool = False,
) -> None:
    base = base or Path(__file__).resolve().parents[1]

    # Step 1: 扫描本地 PDF
    print("[Step 1/4] 扫描本地 PDF 目录 …")
    pdf_root = find_pdf_root(base)
    print(f"  PDF 根目录：{pdf_root}")
    local_pdfs = scan_local_pdfs(pdf_root)
    print(f"  发现 {len(local_pdfs)} 个 PDF 文件")

    # Step 2: 读取并更新可下载 CSV
    print("\n[Step 2/4] 匹配本地 PDF 到报告行 …")
    dl_path = base / DOWNLOADABLE_CSV
    if not dl_path.exists():
        # 若中间表不存在，尝试从最终报告重建（允许在报告生成后单独运行 sync_and_build.py）
        report_csv = base / "paper_search_report.csv"
        if report_csv.exists():
            bootstrap_from_report(report_csv, dl_path)
        else:
            print(f"  [错误] 找不到 {dl_path}，请先运行：python3 paper_search_crawler.py")
            sys.exit(1)

    rows = read_csv(dl_path)
    if not rows:
        # 中间表为空：尝试从最终报告重建
        report_csv = base / "paper_search_report.csv"
        if report_csv.exists():
            bootstrap_from_report(report_csv, dl_path)
            rows = read_csv(dl_path)
        if not rows:
            print("  [错误] 中间表为空且无法从报告重建，请先运行：python3 paper_search_crawler.py")
            sys.exit(1)
    print(f"  读取 {len(rows)} 行（{dl_path.name}）")

    rename_label = "[预览] 重命名" if dry_run else "Step 3.5/4: 重命名本地 PDF"

    # 若启用 rename：先改名（更新 pdf.path），再重新匹配和写入，保证报告使用新路径
    if rename_pdfs:
        print(f"\n{rename_label} …")
        n_renamed, rename_logs = rename_pdfs_by_title(local_pdfs, root=pdf_root, dry_run=dry_run)
        for log in rename_logs:
            print(f"  {log}")
        if n_renamed:
            print(f"  {'[预览]' if dry_run else '✓'} 共 {n_renamed} 个文件{'将' if dry_run else ''}被改名")
        else:
            print("  （无需改名或 PDF 元数据无可读标题）")

        # 如果 dry_run，按旧路径生成报告，不改写 CSV
        if dry_run:
            match_pdfs_to_rows(local_pdfs, rows)   # 不改名，只按旧路径匹配
            update_download_status(rows, base)
            write_csv(dl_path, rows)
            matched = sum(1 for r in rows if r.get("本地PDF","").strip())
            print(f"  ✓ 已匹配 {matched} 篇论文到本地 PDF")
            n_classic = inject_missing_classics(rows, local_pdfs)
            if n_classic:
                print(f"  ✓ 已补全 {n_classic} 篇缺失的经典必读论文")
            downloaded = sum(1 for r in rows if (r.get("下载状态","") or "") in ("exists","downloaded"))
            print(f"  ✓ 下载状态更新：{downloaded} 篇本地已有")

    # 非 rename 模式，或 rename 实际执行后（非 dry_run）：以新路径重新匹配并写入中间 CSV
    if not (rename_pdfs and dry_run):
        match_pdfs_to_rows(local_pdfs, rows)
        matched = sum(1 for r in rows if r.get("本地PDF", "").strip())
        print(f"  ✓ 已匹配 {matched} 篇论文到本地 PDF")

        # Step 2.5: 补全缺失的经典必读论文
        n_classic = inject_missing_classics(rows, local_pdfs)
        if n_classic:
            print(f"  ✓ 已补全 {n_classic} 篇缺失的经典必读论文")
        print(f"  → 当前总行数：{len(rows)}")

        # Step 3: 更新下载状态写回
        update_download_status(rows, base)
        downloaded = sum(1 for r in rows if (r.get("下载状态", "") or "") in ("exists", "downloaded"))
        print(f"  ✓ 下载状态更新：{downloaded} 篇本地已有")
        write_csv(dl_path, rows)
        print(f"  ✓ 已写回 {dl_path.name}")

    # 未匹配统计
    if print_unmatched:
        unmatched_pdfs = [p for p in local_pdfs if p.matched_index is None]
        unmatched_rows = [r for r in rows
                          if not r.get("本地PDF", "").strip()
                          and (r.get("下载状态", "") != "exists")
                          and not r.get("经典必读种子", "")]
        print(f"\n  ── 本地有 PDF 但报告未覆盖：{len(unmatched_rows)} 篇 ──")
        for r in unmatched_rows[:10]:
            print(f"    • {r.get('标题', '')[:70]}")
        if len(unmatched_rows) > 10:
            print(f"    … 还有 {len(unmatched_rows) - 10} 篇")

        really_unmatched_pdfs = [p for p in unmatched_pdfs
                                 if p.match_score < MATCH_THRESHOLD]
        print(f"\n  ── 本地 PDF 未匹配任何报告行：{len(really_unmatched_pdfs)} 个 ──")
        for p in really_unmatched_pdfs[:10]:
            print(f"    • {p.path.name}")
        if len(really_unmatched_pdfs) > 10:
            print(f"    … 还有 {len(really_unmatched_pdfs) - 10} 个")

    # Step 4: 生成最终报告
    if run_build:
        print("\n[Step 3/4] 生成最终报告 …")
        from reporting.unified import build as build_unified
        html_path, csv_path, count = build_unified(base)
        print(f"  ✓ 报告已生成：{html_path.name} / {csv_path.name}（{count} 行）")

        # 汇总
        report_rows = read_csv(csv_path)
        total   = len(report_rows)
        has_pdf = sum(1 for r in report_rows if r.get("本地PDF", "").strip())
        missing = sum(1 for r in report_rows
                      if (r.get("下载状态", "") or "") not in ("exists", "downloaded"))
        print(f"\n  ┌─ 报告汇总 ──────────────────────────┐")
        print(f"  │ 总论文数     : {total:<24}│")
        print(f"  │ 本地已有 PDF : {has_pdf:<24}│")
        print(f"  │ 未下载/无链接: {missing:<24}│")
        print(f"  └─────────────────────────────────────┘")

    # 始终清理中间文件
    _cleanup_intermediates(base)


def _cleanup_intermediates(base: Path) -> None:
    """删除所有 .csv/.html 中间文件，只保留最终报告。"""
    keep_files = {
        "paper_search_report.csv",
        "paper_search_report.html",
    }
    keep_files.update({f.name for f in base.glob("*.py")})

    removed: list[str] = []
    for child in sorted(base.iterdir()):
        if child.is_file() and child.suffix in {".csv", ".html"} and child.name not in keep_files:
            try:
                child.unlink()
                removed.append(child.name)
            except OSError:
                pass
        elif child.is_dir() and child.name == "local_pdfs_not_in_search":
            try:
                shutil.rmtree(child)
                removed.append(child.name + "/")
            except OSError:
                pass
    if removed:
        print(f"\n[清理] 已删除中间文件：{', '.join(removed)}")


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="同步本地 PDF 状态并生成最终报告")
    parser.add_argument("--no-build", action="store_true",
                        help="只同步状态，不重新生成报告")
    parser.add_argument("--no-rename", action="store_false", dest="rename_pdfs",
                        help="跳过 PDF 重命名（默认每次运行均自动重命名）")
    parser.add_argument("--dry-run", action="store_true",
                        help="预览 PDF 重命名结果但不实际执行文件改名（默认做预览）")
    parser.add_argument("--base", type=Path, default=None,
                        help="项目根目录（默认脚本所在目录）")
    args = parser.parse_args(argv)

    sync_and_build(
        base=args.base,
        run_build=not args.no_build,
        rename_pdfs=getattr(args, "rename_pdfs", True),
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
