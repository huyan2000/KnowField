#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations
"""
顶会顶刊论文搜索爬虫 —— 基于博士研究计划关键词
研究主题：Scalable and Adaptive Federated Learning for Heterogeneous 6G-Edge Environments
"""

import csv
import argparse
import hashlib
import json
import os
import random
import re
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace

try:
    import requests
except ImportError:
    requests = None

try:
    from scholarly import scholarly
except ImportError:
    scholarly = None

# S2 metadata API：统一 UA；API key 只从环境变量读取，避免把失效/私有 key 写死在代码里。
# 使用方式：export S2_API_KEY='你的key'
S2_API_KEY = os.getenv("S2_API_KEY", "").strip()
S2_HEADERS = {"User-Agent": "paper-radar/0.2"}
if S2_API_KEY:
    S2_HEADERS["x-api-key"] = S2_API_KEY

# 缓存目录：永久保存，避免重复请求（手动删除 .s2_cache 可强制刷新）
S2_CACHE_DIR = Path(__file__).resolve().parents[1] / ".s2_cache"

# 已见论文记录：用于检测新论文
SEEN_PAPERS_PATH = Path(__file__).resolve().parents[1] / ".seen_papers.json"

# 请求间隔：默认比原脚本快，遇到 429 仍会按 Retry-After/指数退避等待。
QUERY_PAUSE_SECONDS = float(os.getenv("PAPER_SEARCH_QUERY_PAUSE", "1.0"))
PAGE_PAUSE_SECONDS = float(os.getenv("PAPER_SEARCH_PAGE_PAUSE", "1.0"))


def _polite_pause(seconds: float):
    if seconds and seconds > 0:
        time.sleep(seconds + random.random() * min(seconds, 1.0))


# 轨道 A：目标相关 FL 机制
# 聚焦最终目标：面向异构 6G/Edge 的自治/自适应联邦学习系统。
DEFAULT_QUERIES = [
    # === G1: 自主闭环聚合 + 客户端可靠性/贡献评估 ===
    "federated learning divergence-based adaptive aggregation non-iid",
    "federated learning gradient divergence weighted aggregation heterogeneous",
    "federated learning validation-free adaptive aggregation",
    "federated learning server-side validation set aggregation",
    "federated learning reliability-aware adaptive aggregation",
    "federated learning trust-aware client aggregation non-iid",
    "federated learning quality-aware model aggregation validation set",
    "federated learning contribution-aware client weighting",
    "federated learning robust aggregation non-iid data heterogeneity",
    "byzantine robust federated learning adaptive aggregation heterogeneous",
    "federated learning poisoning robust aggregation fairness",
    "federated optimization heterogeneous federated averaging convergence",
    "federated learning client selection contribution evaluation",
    "federated learning guided participant selection Oort",
    "federated learning client utility system utility selection",
    "federated learning asynchronous aggregation straggler mitigation",
    "federated learning client clustering data distribution aggregation",
    "federated learning clustered aggregation reliability non-iid",
    "federated learning feature alignment heterogeneous representation",
    "federated learning prototype aggregation feature shift",
    "federated learning knowledge distillation aggregation non-iid",
    "federated learning model aggregation weight adaptation dynamic",
    "federated learning update similarity cosine aggregation",
    "federated learning gradient similarity client reliability",
    # === G2: 漂移感知 + 持续适应/自进化 ===
    "federated learning concept drift detection incremental learning",
    "federated learning distributed concept drift",
    "federated learning client-specific concept drift",
    "federated learning drift-aware adaptive aggregation",
    "federated learning dynamic client clustering concept drift",
    "federated learning reactive concept drift mitigation",
    "federated learning data stream concept drift edge",
    "federated learning continual learning drift adaptation edge",
    "continual federated learning catastrophic forgetting global model",
    "federated learning rehearsal-free continual learning",
    "federated learning orthogonal training catastrophic forgetting",
    "federated learning online learning data distribution shift",
    "federated learning non-stationary data clients",
    "federated learning domain adaptation transfer non-stationary",
    "federated learning catastrophic forgetting continual adaptation",
    "federated learning temporal evolving streaming data",
    "concept drift detection online machine learning streaming",
    # === G3: 资源感知个性化 + 模型/设备异构适配 ===
    "federated learning personalized meta-learning resource-aware edge",
    "federated learning meta-learning personalization heterogeneous devices",
    "heterogeneity-aware federated meta learning edge devices",
    "resource-aware personalized federated learning edge",
    "dynamic personalization federated learning non-iid clients",
    "personalized federated learning local adaptation global model",
    "federated learning model heterogeneity different architectures",
    "federated learning knowledge transfer local global personalization",
    "federated learning split learning partial model personalized",
    "split federated learning early exit edge devices label shift",
    "federated learning early exit personalization edge",
    "federated learning fine-tuning local data client adaptation",
    "federated learning FedPer FedRep parameter partitioning layer",
    "federated learning pFedMe Ditto FedBN personalization",
    "federated learning personalized batch normalization feature shift",
    "federated learning state space model catastrophic forgetting edge",
    # === 场景：6G / Edge / Communication ===
    "federated learning 6G edge computing heterogeneous",
    "federated learning zero-touch 6G edge intelligence",
    "federated learning intelligent 6G network management",
    "federated learning network control plane 6G edge",
    "federated learning edge cloud scalable adaptive",
    "federated learning communication compression sparsification gradient",
    "federated learning decentralized peer-to-peer gossip protocol",
    "federated learning IoT resource constrained wireless devices",
    "federated learning cloud-edge resource allocation scheduling",
    "federated learning UAV resource allocation personalized",
    # === 通用 FL 算法前沿 ===
    "communication efficient federated learning optimization icml neurips",
    "personalized federated learning icml iclr",
    "federated learning survey 2024 2025",
    "federated learning benchmark evaluation comparison 2025",
    "federated learning FedScale benchmark heterogeneity",
]

# 轨道 B1：FL 系统实现（要求 federated + system/framework/platform）
INFRA_B1_QUERIES = [
    "federated learning system framework deployment",
    "federated learning platform scalable orchestration",
    "federated learning infrastructure kubernetes container",
    "federated learning system architecture edge cloud",
    "federated learning benchmark simulation testbed evaluation",
    "federated learning middleware runtime edge deployment",
    "federated learning edge deployment monitoring kubernetes",
    "federated learning orchestration resource management edge",
    "federated learning self-adaptive system framework",
]

# 轨道 B2：分布式ML系统（不要求 federated，聚焦 training/scheduling/throughput）。
# 默认不检索：这是通用分布式训练备用轨道，博士主线结果不纳入。
INFRA_B2_QUERIES = [
    "distributed training system scheduling heterogeneous cluster",
    "gpu cluster scheduling deep learning training",
    "straggler mitigation distributed machine learning",
    "gradient synchronization training throughput",
    "elastic distributed training system fault tolerance",
    "model parallelism pipeline parallelism distributed training",
    "distributed deep learning communication bandwidth optimization",
    "machine learning system resource scheduling heterogeneous GPU",
    "deep learning training job failure diagnosis cluster",
    "autonomous machine learning infrastructure scheduling",
]

# 轨道 B3：自治系统 / 自适应系统（不要求 federated）
# 用于支撑最终 thesis 框架：MAPE-K、self-adaptation、self-healing、zero-touch。
AUTONOMIC_QUERIES = [
    "autonomic computing MAPE-K self adaptive systems",
    "self-adaptive systems monitor analyze plan execute knowledge",
    "self-adaptive systems survey taxonomy uncertainty",
    "autonomic computing survey MAPE-K feedback loop",
    "software engineering self-adaptive systems research roadmap",
    "architecture-based self-adaptation Rainbow framework",
    "engineering self-adaptive systems feedback loops",
    "requirements uncertainty self-adaptive systems RELAX",
    "runtime models uncertainty self-adaptive systems assurance",
    "decentralized control patterns self-adaptive systems",
    "self-adaptive cloud computing resource management",
    "autonomic cloud resource management reinforcement learning",
    "self-healing cloud edge computing systems",
    "self-optimizing edge computing resource orchestration",
    "zero-touch network management closed-loop automation 6G",
    "zero-touch network management 6G self-adaptive edge",
    "self-X 6G network management self-adaptive",
    "lifelong self-adaptation machine learning systems",
    "autonomous federated learning self-adaptive edge",
    "closed-loop federated learning edge intelligence",
    "self-adaptive federated learning concept drift edge",
]

# 经典必读论文：不受 min_year 限制，直接写入最终报告。
# 作用是补齐 FedAvg / FedProx / Oort / FedScale / MAPE-K 等“必须知道”的根论文，
# 避免主检索只抓近五年时漏掉研究脉络。
CLASSIC_PAPERS = [
    {
        "title": "Communication-Efficient Learning of Deep Networks from Decentralized Data",
        "authors": ["H. Brendan McMahan", "Eider Moore", "Daniel Ramage", "Seth Hampson", "Blaise Aguera y Arcas"],
        "year": 2017,
        "venue": "AISTATS",
        "url": "https://proceedings.mlr.press/v54/mcmahan17a.html",
        "abstract": "经典必读：FedAvg 基础论文，定义了现代联邦学习的基本训练范式，是所有 FL aggregation / communication efficiency 工作的起点。",
        "track": "A",
        "_classic_objectives": ["G1", "G4"],
    },
    {
        "title": "Towards Federated Learning at Scale: System Design",
        "authors": ["Keith Bonawitz", "Hubert Eichner", "Wolfgang Grieskamp", "Dzmitry Huba", "Alex Ingerman"],
        "year": 2019,
        "venue": "MLSys",
        "url": "https://proceedings.mlsys.org/paper_files/paper/2019/hash/bd686fd640be98efaae0091fa301e613-Abstract.html",
        "abstract": "经典必读：大规模 FL 系统设计论文，适合支撑你的系统/部署/自治闭环章节。",
        "track": "B1",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "Federated Optimization in Heterogeneous Networks",
        "authors": ["Tian Li", "Anit Kumar Sahu", "Manzil Zaheer", "Maziar Sanjabi", "Ameet Talwalkar", "Virginia Smith"],
        "year": 2020,
        "venue": "MLSys",
        "url": "https://proceedings.mlsys.org/paper_files/paper/2020/hash/1f5fe83998a09396ebe6477d9475ba0c-Abstract.html",
        "abstract": "经典必读：FedProx，直接对应统计异构和系统异构，是你的 heterogeneous FL 主线基础。",
        "track": "A",
        "_classic_objectives": ["G1", "G4"],
    },
    {
        "title": "SCAFFOLD: Stochastic Controlled Averaging for Federated Learning",
        "authors": ["Sai Praneeth Karimireddy", "Satyen Kale", "Mehryar Mohri", "Sashank Reddi", "Sebastian Stich", "Ananda Theertha Suresh"],
        "year": 2020,
        "venue": "ICML",
        "url": "https://proceedings.mlr.press/v119/karimireddy20a.html",
        "abstract": "经典必读：用 control variates 处理 client drift，是理解非 IID 下聚合偏移和稳定性的关键论文。",
        "track": "A",
        "_classic_objectives": ["G1", "G2"],
    },
    {
        "title": "Tackling the Objective Inconsistency Problem in Heterogeneous Federated Optimization",
        "authors": ["Jianyu Wang", "Qinghua Liu", "Hao Liang", "Gauri Joshi", "H. Vincent Poor"],
        "year": 2020,
        "venue": "NeurIPS",
        "url": "https://proceedings.neurips.cc/paper/2020/hash/564127c03caab942e503ee6f810f54fd-Abstract.html",
        "abstract": "经典必读：FedNova，解释异构本地训练导致的 objective inconsistency，和你的异构聚合主线直接相关。",
        "track": "A",
        "_classic_objectives": ["G1", "G4"],
    },
    {
        "title": "Adaptive Federated Optimization",
        "authors": ["Sashank J. Reddi", "Zachary Charles", "Manzil Zaheer", "Zachary Garrett", "Keith Rush", "Jakub Konečný", "Sanjiv Kumar", "H. Brendan McMahan"],
        "year": 2021,
        "venue": "ICLR",
        "url": "https://openreview.net/forum?id=LkFG3lB13U5",
        "abstract": "经典必读：FedAdam/FedYogi/FedAdagrad，适合理解 server-side adaptive optimization 与自适应聚合的边界。",
        "track": "A",
        "_classic_objectives": ["G1"],
    },
    {
        "title": "Oort: Efficient Federated Learning via Guided Participant Selection",
        "authors": ["Fan Lai", "et al."],
        "year": 2021,
        "venue": "OSDI",
        "url": "https://www.usenix.org/conference/osdi21/presentation/lai",
        "abstract": "经典必读：系统效用驱动的客户端选择，和你的 reliability / utility / autonomous client selection 高度相关。",
        "track": "B1",
        "_classic_objectives": ["G1", "G4"],
    },
    {
        "title": "FedScale: Benchmarking Model and System Performance of Federated Learning at Scale",
        "authors": ["Fan Lai", "et al."],
        "year": 2022,
        "venue": "ICML",
        "url": "https://proceedings.mlr.press/v162/lai22a.html",
        "abstract": "经典必读：大规模 FL benchmark / runtime，对你评估异构、可扩展、系统性能很重要。",
        "track": "B1",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "Federated Learning on Non-IID Features via Local Batch Normalization",
        "authors": ["Xiaoxiao Li", "Meirui Jiang", "Xiaofei Zhang", "Michael Kamp", "Qi Dou"],
        "year": 2021,
        "venue": "ICLR",
        "url": "https://openreview.net/forum?id=6YEQUn0QICG",
        "abstract": "经典必读：FedBN，处理 feature shift，是个性化和本地适配方向的重要基线。",
        "track": "A",
        "_classic_objectives": ["G3"],
    },
    {
        "title": "Personalized Federated Learning with Moreau Envelopes",
        "authors": ["Canh T. Dinh", "Nguyen H. Tran", "Tuan Dung Nguyen"],
        "year": 2020,
        "venue": "NeurIPS",
        "url": "https://proceedings.neurips.cc/paper/2020/hash/f4f1f13c8289ac1b1ee0ff176b56fc60-Abstract.html",
        "abstract": "经典必读：pFedMe，个性化 FL 经典方法，可作为 scalable personalization 的基础对比。",
        "track": "A",
        "_classic_objectives": ["G3"],
    },
    {
        "title": "Ditto: Fair and Robust Federated Learning Through Personalization",
        "authors": ["Tian Li", "Shengyuan Hu", "Ahmad Beirami", "Virginia Smith"],
        "year": 2021,
        "venue": "ICML",
        "url": "https://proceedings.mlr.press/v139/li21h.html",
        "abstract": "经典必读：个性化、鲁棒性和公平性的代表性工作，适合做 personalized FL 强基线。",
        "track": "A",
        "_classic_objectives": ["G3"],
    },
    {
        "title": "Practical Secure Aggregation for Privacy-Preserving Machine Learning",
        "authors": ["Keith Bonawitz", "Vladimir Ivanov", "Ben Kreuter", "Antonio Marcedone", "H. Brendan McMahan"],
        "year": 2017,
        "venue": "CCS",
        "url": "https://dl.acm.org/doi/10.1145/3133956.3133982",
        "abstract": "经典必读：安全聚合基础论文，说明 FL 隐私保护不能只靠“不上传原始数据”。",
        "track": "A",
        "_classic_objectives": ["G1", "G4"],
    },
    {
        "title": "An Architectural Blueprint for Autonomic Computing",
        "authors": ["Autonomic Computing Working Group"],
        "year": 2006,
        "venue": "White Paper",
        "url": "",
        "abstract": "经典必读：MAPE-K / autonomic computing 基础材料，用来支撑你的自治系统框架表述。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "Rainbow: Architecture-Based Self-Adaptation with Reusable Infrastructure",
        "authors": ["David Garlan", "Shang-Wen Cheng", "An-Cheng Huang", "Bradley Schmerl", "Peter Steenkiste"],
        "year": 2004,
        "venue": "IEEE Computer",
        "url": "https://www.cs.cmu.edu/~garlan/publications/RainbowComputer04.pdf",
        "abstract": "经典必读：self-adaptive systems 代表性框架，适合借鉴 monitor-analyze-plan-execute 的系统组织方式。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "A survey of autonomic computing—degrees, models, and applications",
        "authors": ["M. Huebscher", "J. McCann"],
        "year": 2008,
        "venue": "ACM Computing Surveys",
        "url": "https://www.semanticscholar.org/paper/0decbb8696f2b5025977ffce3c03ce7108097fd4",
        "abstract": "经典必读：autonomic computing 综述，梳理自治程度、模型和应用，可用于界定你的系统到底自治到什么层次。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "Software Engineering for Self-Adaptive Systems: A Research Roadmap",
        "authors": ["B. Cheng", "R. de Lemos", "H. Giese", "P. Inverardi", "J. Magee", "J. Andersson"],
        "year": 2009,
        "venue": "Software Engineering for Self-Adaptive Systems",
        "url": "https://www.semanticscholar.org/paper/5c7e1b47e0864c8e9e075389d17c31352b0484ee",
        "abstract": "经典必读：self-adaptive systems 研究路线图，用来组织问题空间、生命周期、运行时模型和评估维度。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "Engineering Self-Adaptive Systems through Feedback Loops",
        "authors": ["Yuriy Brun", "Giovanna Di Marzo Serugendo", "Cristina Gacek", "Holger Giese", "Holger Kienle", "Marin Litoiu"],
        "year": 2009,
        "venue": "Software Engineering for Self-Adaptive Systems",
        "url": "https://www.semanticscholar.org/paper/3c111e31a8a971982520adf51945a402d13ce4da",
        "abstract": "经典必读：反馈环视角的自治系统基础论文，可直接映射到 FL 的监控、分析、决策和执行闭环。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "RELAX: Incorporating Uncertainty into the Specification of Self-Adaptive Systems",
        "authors": ["J. Whittle", "P. Sawyer", "N. Bencomo", "B. Cheng", "J. Bruel"],
        "year": 2009,
        "venue": "IEEE International Requirements Engineering Conference",
        "url": "https://www.semanticscholar.org/paper/c745e8aa0cd62a475c2fd4d20182f6288fea9e66",
        "abstract": "经典必读：面向不确定性需求的自适应系统论文，可支撑异构边缘环境下目标/SLA/资源约束动态变化的论述。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "On Patterns for Decentralized Control in Self-Adaptive Systems",
        "authors": ["Danny Weyns", "Bradley Schmerl", "Vincenzo Grassi", "Sam Malek", "Raffaela Mirandola", "Christian Prehofer"],
        "year": 2010,
        "venue": "Software Engineering for Self-Adaptive Systems",
        "url": "https://www.semanticscholar.org/paper/a6037aaa769ff83fa6704009195c665fe04d626a",
        "abstract": "经典必读：去中心化自治控制模式，适合连接分层/边缘 FL 中多层控制器、边云协同和客户端自治选择。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "ActivFORMS: active formal models for self-adaptation",
        "authors": ["M. U. Iftikhar", "Danny Weyns"],
        "year": 2014,
        "venue": "International Symposium on Software Engineering for Adaptive and Self-Managing Systems",
        "url": "https://www.semanticscholar.org/paper/7542084705c933fb4272555c903a00633e606f2b",
        "abstract": "经典必读：运行时形式化模型驱动自适应，适合作为自治 FL 中 runtime model / knowledge base 的参考。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "Uncertainty in Self-adaptive Systems: A Research Community Perspective",
        "authors": ["Sara Mahdavi-Hezavehi", "Danny Weyns", "Paris Avgeriou", "Radu Calinescu", "Raffaela Mirandola", "Diego Perez-Palacin"],
        "year": 2020,
        "venue": "ACM Transactions on Autonomous and Adaptive Systems",
        "url": "https://www.semanticscholar.org/paper/16e462055481b8b2aa04b8165ed71b3e0270bb27",
        "abstract": "经典必读：自治系统不确定性综述，可支撑 non-IID、concept drift、资源波动和网络波动下的运行时决策。",
        "track": "B3",
        "_classic_objectives": ["G2", "G4"],
    },
    {
        "title": "Self-adaptive systems: A survey of current approaches, research challenges and applications",
        "authors": ["Frank D. Macias-Escriva", "R. Haber", "Raul M. del Toro", "Vicente Hernandez"],
        "year": 2013,
        "venue": "Expert Systems with Applications",
        "url": "https://www.semanticscholar.org/paper/8646740a86c65a531c571fe312f8e3189032672c",
        "abstract": "经典必读：self-adaptive systems 综述，适合补充自治系统术语、应用类型和研究挑战。",
        "track": "B3",
        "_classic_objectives": ["G4"],
    },
    {
        "title": "A Survey on Concept Drift Adaptation",
        "authors": ["Jie Lu", "Anjin Liu", "Fan Dong", "Feng Gu", "Joao Gama", "Guangquan Zhang"],
        "year": 2018,
        "venue": "ACM Computing Surveys",
        "url": "https://dl.acm.org/doi/10.1145/3190525",
        "abstract": "经典必读：概念漂移综述，适合作为 FL drift detection/adaptation 的背景理论入口。",
        "track": "A",
        "_classic_objectives": ["G2"],
    },
]

# 本地 PHD-Buyya 反向补全论文：这些论文已经在本地 PDF 集合中，
# 但没有被当前关键词/阈值组合稳定召回。作为 local seed 加入，不改原有评分规则。
LOCAL_COMPLEMENT_PAPERS = [
    {
        "title": "Adaptive aggregation for federated learning using representation ability based on feature alignment",
        "authors": ["Fujun Pei", "Yunpeng Xie", "Mingjie Shi", "TianTian Xu"],
        "year": 2025,
        "venue": "Knowledge-Based Systems",
        "url": "https://doi.org/10.1016/j.knosys.2025.113560",
        "abstract": "本地补充：PHD-Buyya 已有 PDF。围绕 feature alignment 和 representation ability 做自适应聚合，补齐当前爬虫对异构聚合/特征对齐类工作的漏召回。",
        "track": "A",
        "_classic_objectives": ["G1", "G3"],
        "_score": 98,
        "_seed_label": "本地补充",
        "_seed_source": "Local PDF Seed",
    },
    {
        "title": "A Heterogeneity-Aware Adaptive Federated Learning Framework for Short-Term Forecasting in Electric IoT Systems",
        "authors": ["Cheng Tong", "Linghua Zhang", "Yin Ding", "Dong Yue"],
        "year": 2025,
        "venue": "IEEE Internet of Things Journal",
        "url": "https://doi.org/10.1109/JIOT.2025.3528545",
        "abstract": "本地补充：PHD-Buyya 已有 PDF。FedHA/FedHAL 结合异步聚合、知识蒸馏和轻量通信，适合边缘 IoT 异构与资源约束 FL 背景。",
        "track": "A",
        "_classic_objectives": ["G1", "G3", "G4"],
        "_score": 98,
        "_seed_label": "本地补充",
        "_seed_source": "Local PDF Seed",
    },
    {
        "title": "Federated Learning With Client Clustering Selection and Quality-Aware Model Aggregation",
        "authors": ["Y. Peng", "C. Wang", "H. Shi", "R. Ma", "H. Guan", "Hanbo Yang"],
        "year": 2025,
        "venue": "IEEE Internet of Things Journal",
        "url": "https://doi.org/10.1109/JIOT.2025.3572901",
        "abstract": "本地补充：PHD-Buyya 已有 PDF。Fed-CCSQMA 结合客户端聚类选择和质量感知聚合，直接对应 client selection / aggregation / IIoT heterogeneity。",
        "track": "A",
        "_classic_objectives": ["G1", "G3"],
        "_score": 98,
        "_seed_label": "本地补充",
        "_seed_source": "Local PDF Seed",
    },
    {
        "title": "GossipFL: A Decentralized Federated Learning Framework With Sparsified and Adaptive Communication",
        "authors": ["Zhenheng Tang", "Shaohuai Shi", "Bo Li", "Xiaowen Chu"],
        "year": 2023,
        "venue": "IEEE Transactions on Parallel and Distributed Systems",
        "url": "https://doi.org/10.1109/TPDS.2022.3230938",
        "abstract": "本地补充：PHD-Buyya 已有 PDF。去中心化 FL、稀疏化通信和自适应 gossip 矩阵，适合补充自治/边缘 FL 中网络通信瓶颈与去中心化控制。",
        "track": "B1",
        "_classic_objectives": ["G1", "G4"],
        "_score": 98,
        "_seed_label": "本地补充",
        "_seed_source": "Local PDF Seed",
    },
]
# 轨道 B1/B2 共享的系统venue（B1可以使用更宽的列表）
INFRA_VENUE_ALIASES = {
    "osdi": ["osdi"],
    "sosp": ["sosp"],
    "nsdi": ["nsdi"],
    "eurosys": ["eurosys"],
    "socc": ["socc", "acm symposium on cloud computing"],
    "atc": ["usenix atc", "annual technical conference"],
    "tpds": ["tpds", "transactions on parallel and distributed systems"],
    "tcc": ["transactions on cloud computing", "tcc"],
    "imc": ["internet measurement conference", "imc"],
    "sigcomm": ["sigcomm"],
    "sc": ["supercomputing", "sc'"],
    "cluster": ["cluster"],
    "ccgrid": ["ccgrid"],
}

AUTONOMIC_VENUE_ALIASES = {
    # Software engineering / self-adaptive systems
    "icse": ["icse"],
    "fse": ["fse", "foundations of software engineering"],
    "seams": ["seams", "software engineering for adaptive and self-managing systems"],
    "acsos": ["acsos", "autonomic computing and self-organizing systems"],
    "icac": ["icac", "international conference on autonomic computing"],
    "tse": ["transactions on software engineering", "tse"],
    "tosem": ["transactions on software engineering and methodology", "tosem"],
    "taas": ["transactions on autonomous and adaptive systems", "taas"],
    "csur": ["computing surveys", "csur"],
    # Systems / cloud / edge
    "osdi": ["osdi"],
    "sosp": ["sosp"],
    "nsdi": ["nsdi"],
    "eurosys": ["eurosys"],
    "socc": ["socc", "acm symposium on cloud computing"],
    "atc": ["usenix atc", "annual technical conference"],
    "tpds": ["tpds", "transactions on parallel and distributed systems"],
    "tcc": ["transactions on cloud computing", "tcc"],
    "tmc": ["transactions on mobile computing", "tmc"],
    # Networking / 6G
    "jsac": ["jsac", "selected areas in communications"],
    "tnsm": ["transactions on network and service management", "tnsm"],
}

# 轨道 B2 专用：仅保留系统社区核心venue（避免混进应用系统/HPC工程论文）
B2_CORE_VENUES = {
    "osdi": ["osdi"],
    "sosp": ["sosp"],
    "nsdi": ["nsdi"],
    "eurosys": ["eurosys"],
    "socc": ["socc", "acm symposium on cloud computing"],
    "atc": ["usenix atc", "annual technical conference"],
    "sc": ["supercomputing", "sc'"],
}

# 轨道 B1 专用关键词（FL系统实现，必须包含federated + 系统venue）
INFRA_B1_TERMS = [
    "federated",  # B1必须与FL相关
    "system", "framework", "platform", "architecture",
    "deployment", "orchestration", "infrastructure",
    "kubernetes", "container", "scalable", "scalability",
    "edge", "edge-cloud", "edge cloud", "6g",
]

# 轨道 B2 专用关键词（分布式ML系统，不要求federated）
INFRA_B2_TERMS = [
    "training", "distributed training", "deep learning",
    "scheduling", "scheduler", "cluster", "workload",
    "gpu", "accelerator", "straggler", "mitigation",
    "gradient", "synchronization", "throughput",
    "heterogeneous", "elastic", "fault tolerance",
    "allreduce", "parameter server", "communication",
]

STRICT_MIN_SCORE = 9  # 最终结果统一阈值；低于 9 的只留在缓存/原始调试中，不进入报告。
INFRA_B1_MIN_SCORE = STRICT_MIN_SCORE  # B1阈值（FL系统实现）
INFRA_B2_MIN_SCORE = STRICT_MIN_SCORE  # B2默认不跑；保留函数用于必要时手动扩展。
AUTONOMIC_MIN_SCORE = STRICT_MIN_SCORE  # B3阈值（自治/自适应系统）

# 仅保留：系统/云/分布式/通信 + ML 顶会顶刊（与 FL + 6G/Edge/Infra 相关）
VENUE_ALIASES = {
    # Systems
    "osdi": ["osdi"],
    "sosp": ["sosp"],
    "eurosys": ["eurosys"],
    "socc": ["socc", "acm symposium on cloud computing"],
    "atc": ["usenix atc", "annual technical conference"],
    "nsdi": ["nsdi"],
    "tpds": ["tpds", "transactions on parallel and distributed systems"],
    "tcc": ["transactions on cloud computing", "tcc"],
    "tmc": ["transactions on mobile computing", "tmc"],
    "iotj": ["iotj", "internet of things journal"],
    "tvt": ["tvt", "transactions on vehicular technology"],
    "jsac": ["jsac", "selected areas in communications"],
    # Data / DB
    "vldb": ["vldb"],
    "sigmod": ["sigmod"],
    # ML（只用缩写，避免 ICMLCN 这类 substring 误判）
    "neurips": ["neurips", "nips"],
    "icml": ["icml"],
    "iclr": ["iclr"],
    "aaai": ["aaai"],
    "jmlr": ["jmlr"],
}

# 双维度主题：必须同时满足「主词」+「系统/场景词」，避免单靠 heterogeneous/edge 误收 LLM 等
PRIMARY_TERMS = ["federated", "federated learning"]
SYSTEM_TERMS = [
    "heterogeneous", "non-iid", "non iid", "heterogeneity",
    "edge", "edge-cloud", "fog", "cloud", "6g", "6-g",
    "resource", "scheduling", "orchestration",
    "communication", "latency", "bandwidth",
    "concept drift", "drift detection", "distribution shift", "continual", "adaptive", "personalized", "personalization",
    "distributed", "decentralized",
    "divergence", "divergence-based", "gradient divergence", "meta-learning", "meta learning", "resource-aware", "resource aware", "scalable",
    "incremental", "incremental learning", "online learning",
]

# 评分过滤：提高阈值，确保论文与RP高度相关（算法轨道更“干净”）
MIN_PAPER_SCORE = STRICT_MIN_SCORE

# 主检索默认从 2021 年开始：覆盖近五年目标相关前沿；更早经典文献建议单独补清单。
DEFAULT_MIN_YEAR = 2021


OBJ1_TERMS = [
    "divergence", "divergence-based", "gradient divergence",
    "adaptive aggregation", "weighted aggregation", "aggregation weight",
    "dynamic weighting", "dynamic weight",
    "validation-free", "server-side validation", "quality-aware",
    "reliability-aware", "trust-aware", "contribution-aware",
    "client utility", "system utility", "update similarity",
    "gradient similarity", "cosine aggregation",
    "robust aggregation", "byzantine robust",
    "non-iid", "non iid", "data heterogeneity",
    "client clustering", "clustered federated",
    "aggregation strategy", "aggregation method",
    "model aggregation", "federated aggregation",
    "variance reduction", "control variate",
    "client selection", "participant selection",
]
OBJ2_TERMS = [
    "concept drift", "drift detection", "distribution shift",
    "data drift", "model drift", "temporal drift",
    "client-specific concept drift", "distributed concept drift",
    "drift-aware", "reactive concept drift", "retraining trigger",
    "continual learning", "incremental learning", "online learning",
    "lifelong learning", "catastrophic forgetting",
    "non-stationary", "evolving data", "streaming data",
    "adaptive update", "model adaptation",
]
OBJ3_TERMS = [
    "personalization", "personalized", "personal model",
    "meta-learning", "meta learning", "maml",
    "fedper", "fedrep", "per-fedavg",
    "fedbn", "pfedme", "ditto", "fedamp",
    "local adaptation", "local fine-tuning", "local fine tuning",
    "model heterogeneity", "heterogeneous model",
    "device heterogeneity", "resource-aware", "resource aware",
    "knowledge distillation", "knowledge transfer",
    "split learning", "split federated", "early exit",
    "parameter partitioning",
]
OBJ4_TERMS = [
    "system", "framework", "platform", "architecture",
    "deployment", "orchestration",
    "kubernetes", "container", "benchmark", "testbed",
    "resource management", "resource allocation", "scheduling",
    "straggler", "dropout", "latency", "bandwidth", "energy",
    "cloud-edge", "edge-cloud",
    "self-adaptive", "self adaptive", "self-evolving", "autonomous",
    "autonomic", "mape-k", "self-optimizing", "self-healing",
    "monitor analyze plan execute", "feedback loop", "self-x",
    "zero-touch", "zero touch",
]


def match_objectives(p: dict) -> list:
    """返回论文匹配的核心目标列表，如 ['G1', 'G3']。"""
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    objs = []
    if any(t in text for t in OBJ1_TERMS):
        objs.append("G1")
    if any(t in text for t in OBJ2_TERMS):
        objs.append("G2")
    if any(t in text for t in OBJ3_TERMS):
        objs.append("G3")
    if any(t in text for t in OBJ4_TERMS):
        objs.append("G4")
    return objs


def is_on_topic(p: dict) -> bool:
    """必须同时包含主词（federated）与至少一个系统/场景词，避免误收纯 LLM、distillation 等。"""
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    has_primary = any(t in text for t in PRIMARY_TERMS)
    has_system = any(t in text for t in SYSTEM_TERMS)
    return has_primary and has_system


def paper_score(p: dict) -> int:
    """轨道 A：论文与 RP 主线贴合度。+3 federated, +2 系统词, +2 RP核心创新点, +1 算法关键词, +1 顶会顶刊, +1 引用>5。"""
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    score = 0
    if any(t in text for t in PRIMARY_TERMS):
        score += 3  # 提高federated权重
    if any(t in text for t in SYSTEM_TERMS):
        score += 2
    # RP核心创新点（提高权重，确保聚焦）
    # 创新点1：divergence-based adaptive aggregation
    if any(t in text for t in ["divergence", "divergence-based", "gradient divergence"]):
        score += 2
    elif any(t in text for t in ["adaptive aggregation", "weighted aggregation"]):
        score += 1
    # 创新点2：concept drift detection and incremental update
    if any(t in text for t in ["concept drift", "drift detection", "distribution shift"]):
        score += 2
    if any(t in text for t in ["incremental", "incremental learning", "continual learning", "online learning"]):
        score += 1
    # 创新点3：personalized meta-learning
    if any(t in text for t in ["meta-learning", "meta learning"]):
        score += 1
    if any(t in text for t in ["personalized", "personalization"]):
        score += 1
    # 通用 FL 算法关键词（避免混入纯应用论文）
    algo_terms = [
        "aggregation", "optimizer", "optimization", "convergence",
        "client selection", "participant selection",
        "variance reduction", "control variate",
    ]
    if any(t in text for t in algo_terms):
        score += 1
    # RP场景关键词
    if "6g" in text or "6-g" in text:
        score += 1
    if any(t in text for t in ["resource-aware", "resource aware", "scalable"]):
        score += 1
    if is_top_venue(p.get("venue") or ""):
        score += 1
    try:
        c = p.get("citationCount")
        if c is not None and int(c) > 5:
            score += 1
    except (TypeError, ValueError):
        pass
    return score


def infra_b1_score(p: dict) -> int:
    """轨道 B1：FL 系统实现，必须包含 federated 且来自系统venue。+4 federated, +3 系统实现词, +2 infra venue, +1 引用>5。"""
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    score = 0
    # B1必须包含federated
    if not any(t in text for t in ["federated", "federated learning"]):
        return 0
    score += 4
    # 强调系统实现词（system/framework/platform），而非场景应用词
    system_terms = ["system", "framework", "platform", "architecture", "deployment", "orchestration", "infrastructure"]
    if any(t in text for t in system_terms):
        score += 3
    elif any(t in text for t in INFRA_B1_TERMS):
        score += 2  # 其他infra词得分较低
    # 必须来自系统venue（OSDI/EuroSys/SoCC/ATC/NSDI/TPDS/TCC/TMC/IoTJ/JSAC 等）
    if not is_infra_venue(p.get("venue") or ""):
        return 0
    score += 2
    try:
        c = p.get("citationCount")
        if c is not None and int(c) > 5:
            score += 1
    except (TypeError, ValueError):
        pass
    return score


def infra_b2_score(p: dict) -> int:
    """轨道 B2：分布式ML系统，不要求 federated。+3 系统词, +3 核心系统顶会, +1 引用>5。"""
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    score = 0
    # B2不要求federated，但必须排除federated论文（避免与B1重复）
    if any(t in text for t in ["federated", "federated learning"]):
        return 0
    # 必须明确是 ML / DL 训练系统，过滤纯 workflow / HPC 调度论文
    if not any(t in text for t in ["training", "deep learning", "machine learning", "neural network"]):
        return 0
    # 必须包含分布式ML系统相关词
    if any(t in text for t in INFRA_B2_TERMS):
        score += 3
    else:
        return 0
    # B2必须来自核心系统顶会（OSDI/SOSP/EuroSys/ATC/SoCC/NSDI/SC）
    if is_b2_venue(p.get("venue") or ""):
        score += 3  # 核心系统顶会权重更高
    else:
        return 0  # 非核心系统顶会直接过滤
    try:
        c = p.get("citationCount")
        if c is not None and int(c) > 5:
            score += 1
    except (TypeError, ValueError):
        pass
    return score


def autonomic_score(p: dict) -> int:
    """轨道 B3：自治系统 / 自适应系统。
    不要求 federated，但必须命中自治系统词 + cloud/edge/network/6G 场景词。
    """
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    score = 0
    strong_autonomic_terms = [
        "autonomic", "self-adaptive", "self adaptive", "self-adaptation",
        "self-evolving", "self evolving", "self-managing",
        "self-optimizing", "self optimizing", "self-healing", "self healing",
        "mape-k", "monitor analyze plan execute", "feedback loop",
        "zero-touch", "zero touch", "self-x", "autoscaling",
    ]
    target_autonomous_terms = [
        "autonomous network management",
        "autonomous cloud", "autonomous edge", "autonomous system",
    ]
    has_strong_autonomic = any(t in text for t in strong_autonomic_terms)
    has_target_autonomous = any(t in text for t in target_autonomous_terms)
    if not (has_strong_autonomic or has_target_autonomous):
        return 0
    # 避免把“autonomous vehicle/driving/platooning”误当成自治系统理论论文。
    if has_target_autonomous and not has_strong_autonomic:
        vehicle_terms = ["autonomous vehicle", "autonomous driving", "vehicle platooning", "vehicular platooning"]
        if any(t in text for t in vehicle_terms):
            return 0
    context_terms = [
        "cloud", "edge", "fog", "iot", "cyber-physical", "6g", "network",
        "machine learning",
        "resource management", "resource allocation", "orchestration", "scheduling",
    ]
    score += 3 if has_strong_autonomic else 2
    if any(t in text for t in context_terms):
        score += 2
    else:
        return 0
    # 与你的目标之间的桥：自治系统论文如果能落到 edge/6G/FL/资源闭环，更优先。
    target_bridge_terms = [
        "federated", "edge", "cloud-edge", "edge-cloud", "6g", "zero-touch",
        "resource orchestration",
        "resource management", "resource allocation", "scheduling",
    ]
    if any(t in text for t in target_bridge_terms):
        score += 2
    if any(t in text for t in ["mape-k", "feedback loop", "monitor analyze plan execute"]):
        score += 1
    if is_autonomic_venue(p.get("venue") or ""):
        score += 2
    try:
        c = p.get("citationCount")
        if c is not None and int(c) > 10:
            score += 1
    except (TypeError, ValueError):
        pass
    return score


def _s2_cache_key(query: str, limit: int, offset: int, min_year: int = None, fields: str = None) -> str:
    """缓存key包含所有影响结果的参数，避免fields变更导致缓存错配"""
    key_str = f"{query}|{limit}|{offset}|{min_year}|{fields or ''}"
    return hashlib.md5(key_str.encode()).hexdigest()


def _s2_cache_get(key: str):
    """命中缓存则返回 (papers, total)，否则 None。永久有效。"""
    if not S2_CACHE_DIR.exists():
        return None
    path = S2_CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
        obj = json.loads(raw)
        return obj.get("data", []), obj.get("total", 0)
    except Exception:
        return None


def _s2_cache_set(key: str, data: list, total: int):
    try:
        S2_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = S2_CACHE_DIR / f"{key}.json"
        path.write_text(
            json.dumps({"data": data, "total": total, "cached_at": time.time()}, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def search_s2_paginated(query: str, max_results: int = 10000, min_year: int = None):
    """分页拉取 S2 搜索结果，每页 100 条。自动拉到底或智能停止。
    停止条件：(1) 没有更多结果 (2) 达到 max_results 或 S2 offset 上限 9999
    (3) 连续 2 页全是低相关论文（标题+摘要不含任何 PRIMARY_TERMS）→ 相关性衰减，停止"""
    page_size = 100
    max_offset = 9999
    max_pages = min(max_results // page_size + 1, max_offset // page_size + 1)
    all_papers = []
    total = 0
    fetched_raw = 0
    empty_relevance_streak = 0
    for page in range(max_pages):
        offset = page * page_size
        if offset > max_offset:
            break
        # 分页停止条件必须基于 API 原始页大小，而不能基于 min_year 过滤后的数量；
        # 否则某页被年份过滤到 <100 篇时会提前停止，漏掉后续页。
        papers_raw, t = search_semantic_scholar(query, limit=page_size, offset=offset, min_year=None)
        if page == 0:
            total = t
        if not papers_raw:
            break
        fetched_raw += len(papers_raw)
        papers = [p for p in papers_raw if p.get("year") and p["year"] >= min_year] if min_year else papers_raw
        all_papers.extend(papers)
        relevant_in_page = sum(
            1 for p in papers_raw
            if any(t in ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower() for t in PRIMARY_TERMS)
        )
        if relevant_in_page == 0:
            empty_relevance_streak += 1
            if empty_relevance_streak >= 2:
                print(f"    [分页] 连续 {empty_relevance_streak} 页无相关论文，停止拉取 (已获取 {len(all_papers)} 篇)")
                break
        else:
            empty_relevance_streak = 0
        if len(papers_raw) < page_size or fetched_raw >= min(total, max_results):
            break
        if page < max_pages - 1:
            _polite_pause(PAGE_PAUSE_SECONDS)
    return all_papers, total


def search_semantic_scholar(query: str, limit: int = 20, offset: int = 0, min_year: int = None):
    """使用 S2 metadata API 搜索论文（单页）；带 24h 缓存。429/5xx/timeout 自动重试（指数退避）。"""
    url = "https://api.semanticscholar.org/graph/v1/paper/search"
    limit = min(limit, 100)
    fields = "paperId,title,authors,year,venue,abstract,url,citationCount,openAccessPdf"
    params = {
        "query": query,
        "limit": limit,
        "offset": offset,
        "fields": fields,
    }
    cache_key = _s2_cache_key(query, limit, offset, min_year, fields)
    cached = _s2_cache_get(cache_key)
    if cached is not None:
        papers, total = cached
        if min_year:
            papers = [p for p in papers if p.get("year") and p["year"] >= min_year]
        print(f"    [缓存] 使用 24h 内缓存，未请求 API")
        return papers, total
    
    max_retries = 5
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, params=params, headers=S2_HEADERS, timeout=15)
            if r.status_code == 200:
                data = r.json()
                papers = data.get("data", [])
                total = data.get("total", 0)
                _s2_cache_set(cache_key, papers, total)
                if min_year:
                    papers = [p for p in papers if p.get("year") and p["year"] >= min_year]
                return papers, total
            elif r.status_code == 429:
                if attempt < max_retries:
                    retry_after = r.headers.get("Retry-After")
                    if retry_after:
                        try:
                            wait_time = float(retry_after) + random.random() * 3
                        except ValueError:
                            wait_time = 15 * (2 ** attempt) + random.random() * 5
                    else:
                        wait_time = 15 * (2 ** attempt) + random.random() * 5
                    wait_time = min(wait_time, 300)
                    print(f"    [S2] 429 限流，等待 {wait_time:.1f} 秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    [S2] 429 限流，已重试 {max_retries} 次，跳过本查询")
                    return [], 0
            elif r.status_code >= 500:
                if attempt < max_retries:
                    wait_time = 3 * (2 ** attempt) + random.random() * 2
                    print(f"    [S2] 服务器错误 {r.status_code}，等待 {wait_time:.1f} 秒后重试 ({attempt+1}/{max_retries})")
                    time.sleep(wait_time)
                    continue
                else:
                    print(f"    [S2] 服务器错误 {r.status_code}，已重试 {max_retries} 次，跳过")
                    return [], 0
            elif r.status_code == 403 and S2_HEADERS.get("x-api-key"):
                print("    [S2] 403：当前 S2_API_KEY 被拒绝，将退回匿名请求重试一次。")
                S2_HEADERS.pop("x-api-key", None)
                try:
                    r = requests.get(url, params=params, headers=S2_HEADERS, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        papers = data.get("data", [])
                        total = data.get("total", 0)
                        _s2_cache_set(cache_key, papers, total)
                        if min_year:
                            papers = [p for p in papers if p.get("year") and p["year"] >= min_year]
                        return papers, total
                except Exception:
                    pass
                r.raise_for_status()
            else:
                r.raise_for_status()
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            if attempt < max_retries:
                wait_time = 3 * (2 ** attempt) + random.random() * 2
                print(f"    [S2] 网络错误 ({type(e).__name__})，等待 {wait_time:.1f} 秒后重试 ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
            else:
                print(f"    [S2] 网络错误，已重试 {max_retries} 次: {e}")
                return [], 0
        except Exception as e:
            print(f"    [S2] 请求失败: {e}")
            return [], 0
    return [], 0


def _normalize_s2_paper(p: dict, source: str = "semantic_scholar") -> dict:
    """把 S2 返回的 paper 对象规范成报告使用的字段。"""
    p = dict(p or {})
    p["source"] = source
    authors = p.get("authors") or []
    p["authors"] = [a.get("name") for a in authors if isinstance(a, dict)] if authors else []
    return p


def find_s2_paper_id_by_title(title: str) -> str | None:
    """经典论文没有 paperId 时，用标题在 S2 中反查 paperId。"""
    if not title:
        return None
    papers, _ = search_semantic_scholar(title, limit=5, offset=0, min_year=None)
    target = _normalize_title(title)
    for p in papers:
        if _normalize_title(p.get("title")) == target:
            return p.get("paperId")
    return papers[0].get("paperId") if papers else None


def fetch_s2_paper_edges(paper_id: str, edge: str, limit: int = 50, offset: int = 0, min_year: int = None):
    """拉取某篇论文的 citations 或 references，用于 snowball 扩展。"""
    if not paper_id or edge not in {"citations", "references"}:
        return [], 0
    paper_field = "citingPaper" if edge == "citations" else "citedPaper"
    fields = ",".join([
        f"{paper_field}.paperId",
        f"{paper_field}.title",
        f"{paper_field}.authors",
        f"{paper_field}.year",
        f"{paper_field}.venue",
        f"{paper_field}.abstract",
        f"{paper_field}.url",
        f"{paper_field}.citationCount",
        f"{paper_field}.openAccessPdf",
    ])
    limit = min(limit, 100)
    params = {"limit": limit, "offset": offset, "fields": fields}
    cache_key = _s2_cache_key(f"edge:{paper_id}:{edge}", limit, offset, min_year, fields)
    cached = _s2_cache_get(cache_key)
    if cached is not None:
        papers, total = cached
        if min_year:
            papers = [p for p in papers if p.get("year") and p["year"] >= min_year]
        return papers, total

    url = f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}/{edge}"
    max_retries = 4
    for attempt in range(max_retries + 1):
        try:
            r = requests.get(url, params=params, headers=S2_HEADERS, timeout=20)
            if r.status_code == 200:
                data = r.json()
                rows = data.get("data") or []
                papers = []
                for row in rows:
                    p = row.get(paper_field) or {}
                    if p and p.get("title"):
                        papers.append(_normalize_s2_paper(p, source=f"s2_{edge}"))
                total = data.get("total", 0)
                _s2_cache_set(cache_key, papers, total)
                if min_year:
                    papers = [p for p in papers if p.get("year") and p["year"] >= min_year]
                return papers, total
            if r.status_code == 429 and attempt < max_retries:
                retry_after = r.headers.get("Retry-After")
                try:
                    wait_time = float(retry_after) if retry_after else 15 * (2 ** attempt)
                except ValueError:
                    wait_time = 15 * (2 ** attempt)
                wait_time = min(wait_time + random.random() * 3, 300)
                print(f"    [Snowball] 429 限流，等待 {wait_time:.1f} 秒后重试 ({attempt+1}/{max_retries})")
                time.sleep(wait_time)
                continue
            if r.status_code >= 500 and attempt < max_retries:
                wait_time = min(3 * (2 ** attempt) + random.random() * 2, 60)
                print(f"    [Snowball] 服务器错误 {r.status_code}，等待 {wait_time:.1f} 秒后重试")
                time.sleep(wait_time)
                continue
            r.raise_for_status()
        except Exception as e:
            if attempt < max_retries:
                time.sleep(min(3 * (2 ** attempt) + random.random() * 2, 60))
                continue
            print(f"    [Snowball] 拉取 {edge} 失败: {e}")
            return [], 0
    return [], 0


def infer_track_for_expanded_paper(p: dict) -> str:
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    if "federated" in text or "federated learning" in text:
        return "A"
    if autonomic_score(p) >= AUTONOMIC_MIN_SCORE:
        return "B3"
    return "S"


def expand_citations_from_papers(
    seed_papers: list,
    existing_papers: list = None,
    seed_limit: int = 30,
    citations_per_seed: int = 50,
    references_per_seed: int = 30,
    min_year: int = DEFAULT_MIN_YEAR,
) -> list:
    """从高分/经典论文出发，拉取引用它的论文和它引用的论文，弥补关键词检索漏召回。"""
    existing_titles = {_normalize_title(p.get("title")) for p in (existing_papers or []) if p.get("title")}
    seeds = sorted(
        seed_papers,
        key=lambda p: (0 if p.get("_classic_seed") else 1, -int(p.get("_score", 0) or 0), -(p.get("year") or 0)),
    )[:seed_limit]
    expanded = []
    for i, seed in enumerate(seeds, 1):
        title = seed.get("title") or ""
        paper_id = seed.get("paperId") or find_s2_paper_id_by_title(title)
        if not paper_id:
            continue
        print(f"\n[Snowball {i}/{len(seeds)}] {title[:90]}")
        for edge, limit in [("citations", citations_per_seed), ("references", references_per_seed)]:
            if limit <= 0:
                continue
            papers, total = fetch_s2_paper_edges(paper_id, edge=edge, limit=limit, min_year=min_year)
            kept = 0
            for p in papers:
                key = _normalize_title(p.get("title"))
                if not key or key in existing_titles:
                    continue
                p["track"] = infer_track_for_expanded_paper(p)
                p["_seed_title"] = title
                p["_snowball_edge"] = edge
                expanded.append(p)
                existing_titles.add(key)
                kept += 1
            print(f"    {edge}: 获取 {len(papers)} 篇 / 保留新候选 {kept} 篇 (总匹配约 {total})")
            _polite_pause(PAGE_PAUSE_SECONDS)
    expanded = dedupe_by_id(expanded)
    score_and_label_papers(expanded)
    # 保留与目标有明显关系的引用扩展候选；最终候选统一 score>=9，避免 6/7/8 分混入。
    useful = []
    for p in expanded:
        track = p.get("track")
        score = int(p.get("_score", 0) or 0)
        if track == "A" and score >= MIN_PAPER_SCORE and p.get("_objectives"):
            useful.append(p)
        elif track == "B3" and score >= AUTONOMIC_MIN_SCORE:
            useful.append(p)
    useful.sort(key=lambda p: (-(int(p.get("_score", 0) or 0)), -(p.get("year") or 0), -(p.get("citationCount") or 0)))
    return useful


def fetch_paper_from_google_scholar(title: str, year_hint: int = None):
    """在 external scholar search 按标题检索，取首条结果并校验标题/年份，返回 dict（含 citationCount、url 等）或 None。"""
    if not scholarly or not title or not title.strip():
        return None
    try:
        query = scholarly.search_pubs(title.strip()[:200])
        pub = next(query, None)
        if pub is None:
            return None
        # scholarly 返回 Publication，可当 dict 用，有 bib、citedby 等
        bib = (pub.get("bib") if isinstance(pub, dict) else None) or getattr(pub, "bib", None) or {}
        if not isinstance(bib, dict):
            bib = {}
        gs_title = bib.get("title", "")
        gs_year = bib.get("pub_year") or bib.get("year") or getattr(pub, "year", None)
        try:
            gs_year = int(gs_year) if gs_year is not None else None
        except (TypeError, ValueError):
            gs_year = None
        if year_hint is not None and gs_year is not None and abs(gs_year - year_hint) > 2:
            return None
        def norm(s):
            return " ".join((s or "").lower().split())[:80]
        if norm(gs_title) != norm(title) and norm(title) not in norm(gs_title) and norm(gs_title) not in norm(title):
            words = set(norm(title).split()) & set(norm(gs_title).split())
            if len(words) < 3:
                return None
        num_citations = getattr(pub, "citedby", None) or getattr(pub, "num_citations", None)
        if num_citations is None and isinstance(pub, dict):
            num_citations = pub.get("citedby") or pub.get("num_citations")
        url = bib.get("pub_url") or getattr(pub, "pub_url", None) or getattr(pub, "url_scholarbib", None)
        if url is None and isinstance(pub, dict):
            url = pub.get("pub_url") or pub.get("url_scholarbib")
        venue = bib.get("venue") or bib.get("journal") or bib.get("publisher")
        return {
            "citationCount": num_citations,
            "url": url,
            "venue": venue,
            "gs_url": url,
        }
    except (StopIteration, Exception):
        return None


def _apply_verification_match(p: dict, match: dict):
    """把比对结果（external scholar search 或 S2）写回 p，并设 verified=True。"""
    p["verified"] = True
    if match.get("venue"):
        p["venue"] = match.get("venue")
    if match.get("citationCount") is not None:
        p["citationCount"] = match["citationCount"]
    # 优先保留 GS 链接便于复查；若无则用原有 url
    if match.get("url") or match.get("gs_url"):
        p["gs_url"] = match.get("gs_url") or match.get("url")
        if not p.get("url"):
            p["url"] = p["gs_url"]


def run_verification(papers: list, limit: int = None):
    """比对确认：在external scholar search中检索，确认是否最终发表在顶会顶刊，并补全引用数、链接。"""
    if not papers:
        return
    if not scholarly:
        print("\n[比对确认] 未安装 scholarly，无法使用外部学术搜索。请运行: pip install scholarly")
        return
    n = len(papers) if (limit is None or limit <= 0) else min(limit, len(papers))
    print(f"\n[比对确认] 在 external scholar search 中对 {n} 篇进行二次检索...")
    for i, p in enumerate(papers[:n]):
        p["verified"] = False
        title = (p.get("title") or "").strip()
        if title:
            match = fetch_paper_from_google_scholar(title, p.get("year"))
            if match:
                _apply_verification_match(p, match)
        if (i + 1) % 5 == 0 or (i + 1) == n:
            print(f"    已比对 {i + 1}/{n} 篇")
        time.sleep(4 + random.random() * 3)  # 5~7 秒间隔，降低被 GS 限流风险
    verified_count = sum(1 for p in papers[:n] if p.get("verified"))
    print(f"    比对完成：{verified_count}/{n} 篇在 external scholar search 上得到确认并已补全信息。")


def _normalize_venue_tokens(venue: str):
    """把 venue 规范化为 token 集合，避免裸 substring 导致 ICMLCN 这类误判。"""
    if not venue:
        return set(), ""
    v = venue.lower()
    # 用非字母数字拆分，再压缩空格
    v_norm = re.sub(r"[^a-z0-9]+", " ", v).strip()
    tokens = set(t for t in v_norm.split() if t)
    return tokens, v_norm


def _alias_match(venue: str, alias_list: list[str]) -> bool:
    """更严格的 alias 匹配：只做 token 级匹配，避免 ICMLCN 这类 substring 误判。
    - 把 alias 也拆成 token，要求 alias 的所有 token 都出现在 venue 的 token 集合中。
    - 不再做裸 substring。
    """
    tokens, _ = _normalize_venue_tokens(venue)
    if not tokens:
        return False
    for alias in alias_list:
        a = (alias or "").lower().strip()
        if not a:
            continue
        alias_tokens = [t for t in re.sub(r"[^a-z0-9]+", " ", a).split() if t]
        if alias_tokens and all(t in tokens for t in alias_tokens):
            return True
    return False


def is_top_venue(venue: str) -> bool:
    """规范化别名匹配，减少误判/漏判。"""
    if not venue:
        return False
    return any(_alias_match(venue, aliases) for aliases in VENUE_ALIASES.values())


def is_infra_venue(venue: str) -> bool:
    """轨道 B1 专用：系统venue（包含TPDS/TCC等，用于FL系统实现）。"""
    if not venue:
        return False
    return any(_alias_match(venue, aliases) for aliases in INFRA_VENUE_ALIASES.values())


def is_b2_venue(venue: str) -> bool:
    """轨道 B2 专用：仅核心系统顶会（OSDI/SOSP/EuroSys/ATC/SoCC/NSDI/SC），避免混进应用系统/HPC工程论文。"""
    if not venue:
        return False
    return any(_alias_match(venue, aliases) for aliases in B2_CORE_VENUES.values())


def is_autonomic_venue(venue: str) -> bool:
    """轨道 B3 专用：自治系统/软件工程/系统/网络相关 venue。"""
    if not venue:
        return False
    return any(_alias_match(venue, aliases) for aliases in AUTONOMIC_VENUE_ALIASES.values())


def write_html_report(papers: list, path: str, min_year: int):
    """生成可在浏览器中打开的 HTML 报告"""
    import html
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in papers:
        title = html.escape((p.get("title") or "").strip())
        url = html.escape((p.get("url") or "").strip())
        authors = html.escape(", ".join((p.get("authors") or [])[:6]))
        if (p.get("authors") or []):
            authors += (" et al." if len(p.get("authors")) > 6 else "")
        year = p.get("year") or "—"
        venue = html.escape((p.get("venue") or "").strip())
        cite = p.get("citationCount")
        cite_str = str(cite) if cite is not None else "—"
        abstract = html.escape(((p.get("abstract") or "").strip())[:400].replace("\n", " "))
        is_top = (
            is_top_venue(p.get("venue") or "")
            or is_infra_venue(p.get("venue") or "")
            or is_autonomic_venue(p.get("venue") or "")
        )
        seed_label = _seed_label(p)
        top = seed_label if p.get("_classic_seed") else ("是" if is_top else "否")
        top_cell = f'<td class="top">{top}</td>' if (is_top or p.get("_classic_seed")) else f"<td>{top}</td>"
        src = _seed_source(p) if p.get("_classic_seed") else "S2"
        # verified_note: "已发表论文"表示S2论文
        if p.get("_classic_seed"):
            verified_cell = f'<td class="verified">{html.escape(seed_label)}</td>'
        elif p.get("verified_note") == "已发表论文":
            verified_cell = '<td>已发表</td>'
        elif p.get("verified"):
            verified_cell = '<td class="verified">是（已确认顶会顶刊）</td>'
        else:
            verified_cell = "<td>否</td>"
        open_link = f'<a href="{url}" target="_blank" rel="noopener">打开</a>' if url else ""
        gs_url = (p.get("gs_url") or "").strip()
        if gs_url and gs_url != url:
            gs_link = f'<a href="{html.escape(gs_url)}" target="_blank" rel="noopener">external scholar search</a>'
            link = f"{open_link} | {gs_link}" if open_link else gs_link
        else:
            link = open_link or "—"
        score_val = p.get("_score", "")
        track = p.get("track") or "A"
        if track == "B1":
            track_label = "B1 (FL系统实现)"
        elif track == "B2":
            track_label = "B2 (分布式ML系统)"
        elif track == "B3":
            track_label = "B3 (自治/自适应系统)"
        else:
            track_label = "A (FL算法)"
        obj_labels = ", ".join(p.get("_objectives", []))
        domain = infer_domain(p)
        domain_cell = f'<td class="domain">{html.escape(domain)}</td>'
        obj_cell = f'<td class="obj">{obj_labels}</td>' if obj_labels else '<td>—</td>'
        new_badge = '<span class="new-badge">🆕 NEW</span>' if p.get("_is_new") else ""
        classic_badge = f'<span class="new-badge">{"经典" if seed_label == "经典必读" else "补充"}</span>' if p.get("_classic_seed") else ""
        star_badge = "⭐ " if p.get("_score", 0) >= 10 else ""
        title_display = f"{star_badge}{title} {classic_badge} {new_badge}".strip()
        is_highlight = p.get("_score", 0) >= 10
        row_class = ' class="highlight"' if is_highlight else ""
        try:
            score_num = int(p.get("_score", 0) or 0)
        except (TypeError, ValueError):
            score_num = 0
        try:
            year_num = int(p.get("year") or 0)
        except (TypeError, ValueError):
            year_num = 0
        try:
            cite_num = int(cite or 0)
        except (TypeError, ValueError):
            cite_num = 0
        row_data = (
            f' data-score="{score_num}" data-year="{year_num}" data-cites="{cite_num}"'
            f' data-domain="{html.escape(domain, quote=True)}"'
            f' data-track="{html.escape(track_label, quote=True)}"'
            f' data-objectives="{html.escape(obj_labels, quote=True)}"'
            f' data-title="{html.escape((p.get("title") or "").lower(), quote=True)}"'
        )
        rows.append(
            f"<tr{row_class}{row_data}><td>{title_display}</td><td>{authors}</td><td>{year}</td><td>{venue}</td>"
            f"<td>{cite_str}</td><td>{link}</td><td>{abstract}</td>{top_cell}<td>{src}</td>{verified_cell}<td>{score_val}</td><td>{track_label}</td>{domain_cell}{obj_cell}</tr>"
        )
    table_rows = "\n".join(rows)
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>论文搜索结果（{min_year} 年及以后 + 经典必读）</title>
<style>
  body {{ font-family: "Segoe UI", "PingFang SC", sans-serif; margin: 1rem 2rem; background: #1a1a2e; color: #eee; }}
  h1 {{ font-size: 1.3rem; color: #a8dadc; }}
  .meta {{ color: #888; margin-bottom: 1rem; }}
  .controls {{ display: flex; flex-wrap: wrap; gap: 0.75rem; align-items: end; margin: 1rem 0; padding: 0.8rem; background: #111827; border: 1px solid #334155; border-radius: 10px; }}
  .controls label {{ display: grid; gap: 0.25rem; color: #a8dadc; font-size: 0.82rem; }}
  .controls select, .controls input {{ min-width: 12rem; background: #0f172a; color: #eee; border: 1px solid #475569; border-radius: 6px; padding: 0.45rem 0.55rem; }}
  .counter {{ color: #f1c40f; font-weight: bold; margin-left: auto; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th, td {{ border: 1px solid #333; padding: 0.5rem 0.6rem; text-align: left; vertical-align: top; }}
  th {{ background: #16213e; color: #a8dadc; position: sticky; top: 0; }}
  tr:nth-child(even) {{ background: #16213e40; }}
  tr:hover {{ background: #0f3460; }}
  a {{ color: #e94560; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .top {{ color: #2ecc71; font-weight: bold; }}
  .verified {{ color: #3498db; }}
  .obj {{ color: #f1c40f; font-weight: bold; }}
  .domain {{ color: #7dd3fc; font-weight: bold; }}
  .highlight {{ background: #2d1f3d !important; border-left: 3px solid #f1c40f; }}
  .new-badge {{ background: #e74c3c; color: #fff; padding: 0.1em 0.4em; border-radius: 3px; font-size: 0.75rem; font-weight: bold; margin-left: 0.3em; }}
  td:nth-child(1) {{ max-width: 22em; }}
  td:nth-child(7) {{ max-width: 28em; font-size: 0.85rem; color: #bbb; }}
</style>
</head>
<body>
<h1>论文搜索结果（{min_year} 年及以后 + 经典必读，共 {len(papers)} 篇）</h1>
<div class="meta">生成时间：{time.strftime("%Y-%m-%d %H:%M", time.localtime())}</div>
<div class="meta">G1=自主闭环聚合 | G2=漂移/持续适应 | G3=资源感知个性化 | G4=自治/自适应系统</div>
<div class="controls">
  <label>领域筛选<select id="domainFilter"><option value="">全部领域</option></select></label>
  <label>轨道筛选<select id="trackFilter"><option value="">全部轨道</option></select></label>
  <label>目标筛选<select id="objectiveFilter"><option value="">全部目标</option><option value="G1">G1 聚合</option><option value="G2">G2 漂移</option><option value="G3">G3 个性化</option><option value="G4">G4 自治/系统</option></select></label>
  <label>排序方式<select id="sortSelect"><option value="score-desc">评分从高到低</option><option value="score-asc">评分从低到高</option><option value="domain-score">领域 → 评分</option><option value="track-score">轨道 → 评分</option><option value="year-desc">年份从新到旧</option><option value="cites-desc">引用从高到低</option></select></label>
  <label>标题搜索<input id="searchBox" placeholder="输入关键词"></label>
  <span class="counter">显示 <span id="visibleCount">{len(papers)}</span> / {len(papers)}</span>
</div>
<table id="paperTable">
<thead><tr><th>标题</th><th>作者</th><th>年份</th><th>出处</th><th>引用</th><th>链接</th><th>摘要</th><th>顶会/顶刊</th><th>来源</th><th>比对确认</th><th>评分</th><th>轨道</th><th>领域</th><th>核心目标</th></tr></thead>
<tbody>
{table_rows}
</tbody>
</table>
<script>
(function() {{
  const tbody = document.querySelector('#paperTable tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const domainFilter = document.getElementById('domainFilter');
  const trackFilter = document.getElementById('trackFilter');
  const objectiveFilter = document.getElementById('objectiveFilter');
  const sortSelect = document.getElementById('sortSelect');
  const searchBox = document.getElementById('searchBox');
  const visibleCount = document.getElementById('visibleCount');

  function fillSelect(select, attr) {{
    Array.from(new Set(rows.map(row => row.dataset[attr]).filter(Boolean)))
      .sort((a, b) => a.localeCompare(b, 'zh-Hans-CN'))
      .forEach(value => {{
        const option = document.createElement('option');
        option.value = value;
        option.textContent = value;
        select.appendChild(option);
      }});
  }}

  function numeric(row, attr) {{
    return Number(row.dataset[attr] || 0);
  }}

  function byText(attr, a, b) {{
    return (a.dataset[attr] || '').localeCompare(b.dataset[attr] || '', 'zh-Hans-CN');
  }}

  function compareRows(a, b) {{
    switch (sortSelect.value) {{
      case 'score-asc':
        return numeric(a, 'score') - numeric(b, 'score') || numeric(b, 'year') - numeric(a, 'year');
      case 'domain-score':
        return byText('domain', a, b) || numeric(b, 'score') - numeric(a, 'score') || numeric(b, 'year') - numeric(a, 'year');
      case 'track-score':
        return byText('track', a, b) || numeric(b, 'score') - numeric(a, 'score') || numeric(b, 'year') - numeric(a, 'year');
      case 'year-desc':
        return numeric(b, 'year') - numeric(a, 'year') || numeric(b, 'score') - numeric(a, 'score');
      case 'cites-desc':
        return numeric(b, 'cites') - numeric(a, 'cites') || numeric(b, 'score') - numeric(a, 'score');
      default:
        return numeric(b, 'score') - numeric(a, 'score') || numeric(b, 'year') - numeric(a, 'year') || numeric(b, 'cites') - numeric(a, 'cites');
    }}
  }}

  function applyControls() {{
    const domain = domainFilter.value;
    const track = trackFilter.value;
    const objective = objectiveFilter.value;
    const keyword = searchBox.value.trim().toLowerCase();
    const visibleRows = rows
      .filter(row => !domain || row.dataset.domain === domain)
      .filter(row => !track || row.dataset.track === track)
      .filter(row => !objective || (row.dataset.objectives || '').includes(objective))
      .filter(row => !keyword || (row.dataset.title || '').includes(keyword))
      .sort(compareRows);
    tbody.innerHTML = '';
    visibleRows.forEach(row => tbody.appendChild(row));
    visibleCount.textContent = visibleRows.length;
  }}

  fillSelect(domainFilter, 'domain');
  fillSelect(trackFilter, 'track');
  [domainFilter, trackFilter, objectiveFilter, sortSelect, searchBox].forEach(el => el.addEventListener('input', applyControls));
  applyControls();
}})();
</script>
</body>
</html>"""
    out.write_text(html_content, encoding="utf-8")
    return out


def score_and_label_papers(papers: list):
    """给论文补充 _score 和 _objectives；保留旧 A/B1/B2 评分逻辑不变。"""
    for p in papers:
        if p.get("_classic_seed"):
            min_seed_score = 99 if _seed_label(p) == "经典必读" else int(p.get("_score", 98) or 98)
            p["_score"] = max(int(p.get("_score", 0) or 0), min_seed_score)
            p["_objectives"] = list(p.get("_classic_objectives") or p.get("_objectives") or [])
            p.setdefault("verified", True)
            p["verified_note"] = _seed_label(p)
            continue
        track = p.get("track") or "A"
        if track == "B1":
            p["_score"] = infra_b1_score(p)
        elif track == "B2":
            p["_score"] = infra_b2_score(p)
        elif track == "B3":
            p["_score"] = autonomic_score(p)
        else:
            p["_score"] = paper_score(p)
        p["_objectives"] = match_objectives(p)


def _track_label(track: str) -> str:
    if track == "B1":
        return "B1 (FL系统实现)"
    if track == "B2":
        return "B2 (分布式ML系统)"
    if track == "B3":
        return "B3 (自治/自适应系统)"
    if track == "S":
        return "S (引用扩展候选)"
    return "A (FL算法)"


def infer_domain(p: dict) -> str:
    """把论文归到便于浏览的研究领域，用于 HTML/CSV 筛选排序。"""
    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
    track = p.get("track") or "A"
    objs = set(p.get("_objectives") or [])
    if track == "B3":
        if any(t in text for t in [
            "mape-k", "feedback loop", "research roadmap", "survey",
            "uncertainty", "requirements", "formal model", "runtime verification",
            "self-adaptive systems", "autonomic computing",
        ]):
            return "自治理论/MAPE-K"
        if any(t in text for t in [
            "zero-touch", "network slicing", "srv6", "service function",
            "network management", "6g", "self-x",
        ]):
            return "自治网络/Zero-touch"
        if any(t in text for t in [
            "cloud", "edge", "fog", "resource", "autoscaling",
            "microservice", "orchestration",
        ]):
            return "云边资源自适应"
        return "自治/自适应系统"
    if track == "B1":
        return "FL系统/平台"
    if "G2" in objs or any(t in text for t in ["concept drift", "continual", "incremental", "non-stationary", "distribution shift"]):
        return "FL漂移/持续学习"
    if "G3" in objs or any(t in text for t in ["personalized", "personalization", "meta-learning", "heterogeneous model", "local adaptation"]):
        return "FL个性化/异构适配"
    if "G1" in objs or any(t in text for t in ["aggregation", "client selection", "participant selection", "divergence", "contribution"]):
        return "FL聚合/客户端选择"
    if any(t in text for t in ["6g", "edge", "iot", "uav", "vehicular", "resource allocation", "scheduling"]):
        return "FL边缘/6G资源"
    return "FL综合"


def write_csv_report(papers: list, output_csv: str):
    """统一写 CSV，供完整结果、宽搜索结果、引用扩展结果复用。"""
    out_path = Path(output_csv)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["标题", "作者", "年份", "出处", "引用数", "链接", "摘要", "是否顶会顶刊", "来源", "比对确认", "评分", "轨道", "核心目标", "领域", "新论文"])
        for p in papers:
            authors_str = "; ".join(p.get("authors") or [])
            src = _seed_source(p) if p.get("_classic_seed") else p.get("source", "S2")
            if p.get("_classic_seed"):
                confirm = _seed_label(p)
            elif p.get("verified"):
                confirm = "是（已确认顶会顶刊）"
            elif p.get("verified_note") == "已发表论文":
                confirm = "已发表"
            else:
                confirm = "否"
            obj_str = ", ".join(p.get("_objectives", []))
            is_new = "🆕" if p.get("_is_new") else ""
            venue = p.get("venue") or ""
            is_top = is_top_venue(venue) or is_infra_venue(venue) or is_autonomic_venue(venue)
            w.writerow([
                (p.get("title") or "").replace("\n", " "),
                authors_str,
                p.get("year") or "",
                venue.replace("\n", " "),
                p.get("citationCount") or "",
                p.get("url") or "",
                (p.get("abstract") or "").replace("\n", " ")[:1000],
                _seed_label(p) if p.get("_classic_seed") else ("是" if is_top else "否"),
                src,
                confirm,
                p.get("_score", ""),
                _track_label(p.get("track") or "A"),
                obj_str,
                infer_domain(p),
                is_new,
            ])
    return out_path


def _load_seen_papers() -> set:
    """加载已见论文 ID 集合。"""
    if not SEEN_PAPERS_PATH.exists():
        return set()
    try:
        data = json.loads(SEEN_PAPERS_PATH.read_text(encoding="utf-8"))
        return set(data)
    except Exception:
        return set()


def _save_seen_papers(seen: set):
    """保存已见论文 ID 集合。"""
    try:
        SEEN_PAPERS_PATH.write_text(
            json.dumps(sorted(seen), ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def _paper_unique_id(p: dict) -> str:
    """论文唯一 ID：优先 paperId，fallback title+year。"""
    pid = p.get("paperId")
    if pid:
        return pid
    title = (p.get("title") or "").strip().lower()
    year = p.get("year") or ""
    return f"{title}|{year}"


def _normalize_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _seed_label(p: dict) -> str:
    return p.get("_seed_label") or ("经典必读" if p.get("_classic_seed") else "")


def _seed_source(p: dict) -> str:
    return p.get("_seed_source") or ("Classic Seed" if p.get("_classic_seed") else p.get("source", "S2"))


def append_classic_papers(papers: list) -> int:
    """追加必读/本地补充 seed；如果检索结果已有同名论文则不重复添加。"""
    seen_by_title = {_normalize_title(p.get("title")): p for p in papers if p.get("title")}
    added = 0
    for raw in CLASSIC_PAPERS + LOCAL_COMPLEMENT_PAPERS:
        key = _normalize_title(raw.get("title"))
        if not key:
            continue
        p = seen_by_title.get(key) or dict(raw)
        for field in ["title", "authors", "year", "venue", "url", "abstract", "track"]:
            if not p.get(field) and raw.get(field):
                p[field] = raw[field]
        p["source"] = p.get("source") or "seed"
        p["_classic_seed"] = True  # 复用 seed 旁路：不受年份/分数过滤影响。
        p["_seed_label"] = raw.get("_seed_label") or p.get("_seed_label") or "经典必读"
        p["_seed_source"] = raw.get("_seed_source") or p.get("_seed_source") or "Classic Seed"
        p["_score"] = max(int(p.get("_score", 0) or 0), int(raw.get("_score", 99) or 99))
        p["_classic_objectives"] = list(raw.get("_classic_objectives") or p.get("_classic_objectives") or [])
        p["_objectives"] = list(p.get("_classic_objectives") or [])
        p["verified"] = True
        p["verified_note"] = _seed_label(p)
        if key not in seen_by_title:
            papers.append(p)
            seen_by_title[key] = p
            added += 1
    return added


def mark_new_papers(papers: list) -> int:
    """标记新论文（_is_new=True），更新 seen_papers.json，返回新论文数。"""
    seen = _load_seen_papers()
    new_count = 0
    for p in papers:
        uid = _paper_unique_id(p)
        if uid not in seen:
            p["_is_new"] = True
            seen.add(uid)
            new_count += 1
        else:
            p["_is_new"] = False
    _save_seen_papers(seen)
    return new_count


def dedupe_by_id(papers: list) -> list:
    """去重：优先用paperId（S2），fallback到title+year+first_author"""
    seen = set()
    out = []
    for p in papers:
        paper_id = p.get("paperId")
        if paper_id:
            if paper_id not in seen:
                seen.add(paper_id)
                out.append(p)
            continue
        
        # Fallback: title + year + first_author
        title = (p.get("title") or "").strip().lower()
        year = p.get("year") or ""
        authors = p.get("authors") or []
        first_author = (authors[0] if authors else "").strip().lower() if isinstance(authors, list) else ""
        fallback_key = f"{title}|{year}|{first_author}"
        if fallback_key and fallback_key not in seen:
            seen.add(fallback_key)
            out.append(p)
    return out


def run_search(
    queries: list = None,
    min_year: int = DEFAULT_MIN_YEAR,
    max_per_query: int = 10000,
    use_s2: bool = True,
    output_csv: str = None,
    output_html: str = None,
    top_only: bool = False,
    verify: bool = False,
    verify_limit: int = None,
    expand_citations: bool = False,
    snowball_seed_limit: int = 30,
    snowball_citations_per_seed: int = 50,
    snowball_references_per_seed: int = 30,
    include_b2: bool = False,
    save_discovery_pool: bool = False,
):
    queries = queries or DEFAULT_QUERIES
    all_papers = []

    # 轨道 A：FL + Edge（S2）
    for i, q in enumerate(queries):
        print(f"\n[轨道 A {i+1}/{len(queries)}] {q}")
        if use_s2:
            papers, total = search_s2_paginated(q, max_results=max_per_query, min_year=min_year)
            for p in papers:
                p["source"] = "semantic_scholar"
                p["authors"] = [a.get("name") for a in p.get("authors") or []]
                p["track"] = "A"
            all_papers.extend(papers)
            print(f"    S2: 获取 {len(papers)} 篇 (总匹配约 {total})")
            _polite_pause(QUERY_PAUSE_SECONDS)

    # 轨道 B1：FL 系统实现（要求 federated + system/framework/platform）
    for i, q in enumerate(INFRA_B1_QUERIES):
        print(f"\n[轨道 B1 {i+1}/{len(INFRA_B1_QUERIES)}] {q}")
        if use_s2:
            papers, total = search_s2_paginated(q, max_results=max_per_query, min_year=min_year)
            added = 0
            for p in papers:
                p["source"] = "semantic_scholar"
                p["authors"] = [a.get("name") for a in p.get("authors") or []]
                text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
                has_federated = any(t in text for t in ["federated", "federated learning"])
                if has_federated:
                    has_system_term = any(t in text for t in ["system", "framework", "platform", "architecture", "deployment", "orchestration"])
                    if is_infra_venue(p.get("venue") or "") or has_system_term or any(t in text for t in INFRA_B1_TERMS):
                        p["track"] = "B1"
                        all_papers.append(p)
                        added += 1
            print(f"    S2: 获取 {len(papers)} 篇（轨道 B1 保留 {added} 篇，总匹配约 {total})")
            _polite_pause(QUERY_PAUSE_SECONDS)
    
    # 轨道 B2：分布式ML备用轨道。默认关闭，避免博士主线被通用训练系统稀释。
    if include_b2:
        for i, q in enumerate(INFRA_B2_QUERIES):
            print(f"\n[轨道 B2 {i+1}/{len(INFRA_B2_QUERIES)}] {q}")
            if use_s2:
                papers, total = search_s2_paginated(q, max_results=max_per_query, min_year=min_year)
                added = 0
                for p in papers:
                    p["source"] = "semantic_scholar"
                    p["authors"] = [a.get("name") for a in p.get("authors") or []]
                    text = ((p.get("title") or "") + " " + (p.get("abstract") or "")).lower()
                    has_federated = any(t in text for t in ["federated", "federated learning"])
                    if not has_federated:
                        if is_b2_venue(p.get("venue") or "") and any(t in text for t in INFRA_B2_TERMS):
                            p["track"] = "B2"
                            all_papers.append(p)
                            added += 1
                print(f"    S2: 获取 {len(papers)} 篇（轨道 B2 保留 {added} 篇，总匹配约 {total})")
                _polite_pause(QUERY_PAUSE_SECONDS)

    # 轨道 B3：自治系统 / 自适应系统（支撑最终目标框架）
    for i, q in enumerate(AUTONOMIC_QUERIES):
        print(f"\n[轨道 B3 {i+1}/{len(AUTONOMIC_QUERIES)}] {q}")
        if use_s2:
            papers, total = search_s2_paginated(q, max_results=max_per_query, min_year=min_year)
            added = 0
            for p in papers:
                p["source"] = "semantic_scholar"
                p["authors"] = [a.get("name") for a in p.get("authors") or []]
                if autonomic_score(p) >= AUTONOMIC_MIN_SCORE:
                    p["track"] = "B3"
                    all_papers.append(p)
                    added += 1
            print(f"    S2: 获取 {len(papers)} 篇（轨道 B3 保留 {added} 篇，总匹配约 {total})")
            _polite_pause(QUERY_PAUSE_SECONDS)

    # 去重（优先用paperId，fallback到title+year+first_author）
    all_papers = dedupe_by_id(all_papers)
    n_seed_added = append_classic_papers(all_papers)
    if n_seed_added:
        print(f"\n[Seed补全] 已追加 {n_seed_added} 篇不受年份限制的经典/本地补充论文")
    score_and_label_papers(all_papers)
    if output_csv and save_discovery_pool:
        discovery_path = Path(output_csv).parent / "papers_search_discovery_all.csv"
        write_csv_report(all_papers, discovery_path)
        print(f"[原始候选池] 已保存未收紧过滤结果: {discovery_path.absolute()}（{len(all_papers)} 篇）")
    total_before_filter = len(all_papers)
    # 过滤：仅保留顶会/顶刊
    if top_only:
        def keep(p):
            if p.get("_classic_seed"):
                return True
            venue = (p.get("venue") or "").strip()
            if is_top_venue(venue) or is_infra_venue(venue) or is_autonomic_venue(venue):
                return True
            return False
        all_papers = [p for p in all_papers if keep(p)]
        dropped = total_before_filter - len(all_papers)
        if dropped > 0:
            n_s2 = sum(1 for p in all_papers if is_top_venue(p.get("venue") or ""))
            print(f"\n[已过滤] 共 {len(all_papers)} 篇（顶会/顶刊 {n_s2} 篇，排除 {dropped} 篇）")
        if len(all_papers) == 0:
            print("  提示：当前 0 篇。可稍后重跑或查看是否被限流。")
    # 评分 + 目标标签
    score_and_label_papers(all_papers)

    # 评分过滤
    n_before_score = len(all_papers)
    all_papers = [
        p for p in all_papers
        if p.get("_classic_seed")
           or (p.get("track") == "B1" and p["_score"] >= INFRA_B1_MIN_SCORE)
           or (p.get("track") == "B3" and p["_score"] >= AUTONOMIC_MIN_SCORE)
           or (p.get("track") not in ["B1", "B2", "B3"] and p["_score"] >= MIN_PAPER_SCORE)
    ]
    if n_before_score > len(all_papers):
        print(f"\n[评分过滤] 最终结果统一 score>={STRICT_MIN_SCORE}（经典必读除外）；B2 默认不进入结果：共 {len(all_papers)} 篇（排除 {n_before_score - len(all_papers)} 篇低分）")

    # 轨道 A 是 FL 主线；非经典论文必须在标题/摘要中明确出现 federated，避免 S2 查询召回泛 6G/智能网络论文。
    n_before_federated = len(all_papers)
    all_papers = [
        p for p in all_papers
        if p.get("_classic_seed")
        or (p.get("track") or "A") != "A"
        or "federated" in (((p.get("title") or "") + " " + (p.get("abstract") or "")).lower())
    ]
    if n_before_federated > len(all_papers):
        print(f"\n[FL主线过滤] 轨道 A 必须显式包含 federated：排除 {n_before_federated - len(all_papers)} 篇泛 6G/智能网络论文，剩余 {len(all_papers)} 篇")

    # 核心目标过滤：轨道 A 必须至少命中一个核心目标（B1/B3 豁免，因为是系统/自治论文）
    n_before_obj = len(all_papers)
    all_papers = [
        p for p in all_papers
        if p.get("_classic_seed") or p.get("track") in ["B1", "B3"] or len(p.get("_objectives", [])) > 0
    ]
    if n_before_obj > len(all_papers):
        print(f"\n[目标过滤] 轨道 A 必须命中 G1/G2/G3/G4 之一：排除 {n_before_obj - len(all_papers)} 篇无关论文，剩余 {len(all_papers)} 篇")
    # 无结果或极少时提示
    if len(all_papers) == 0:
        print("\n未找到符合条件的结果。可能原因：")
        print("  1. --min-year 设得过高（如 2025）：目前该年份论文还很少，建议改为 2023 或 2024。")
        print("  2. 网络或 API 限流，可稍后重试或减少 --per-query。")
        print("\n建议先运行: python a.py  或  python a.py --min-year 2024")
        return []
    if len(all_papers) <= 3 and min_year >= 2025:
        print("\n提示: 2025 年论文目前较少，若想查看更多最新工作，建议使用 --min-year 2024")
    # 排序：默认按评分从高到低；HTML 中仍可切换领域/年份/引用等排序。
    def sort_key(p):
        try:
            s = int(p.get("_score", 0) or 0)
        except (TypeError, ValueError):
            s = 0
        try:
            y = int(p.get("year") or 0)
        except (TypeError, ValueError):
            y = 0
        try:
            c = int(p.get("citationCount") or 0)
        except (TypeError, ValueError):
            c = 0
        return (-s, -y, -c)

    all_papers.sort(key=sort_key)

    # 设置论文属性
    for p in all_papers:
        p.setdefault("track", "A")
        p.setdefault("verified", False)
        p.setdefault("source", "semantic_scholar")
        if p.get("_classic_seed"):
            p["verified_note"] = _seed_label(p)
        else:
            p["verified_note"] = "已发表论文"

    # 标记新论文
    n_new = mark_new_papers(all_papers)

    # 控制台输出
    n_a = sum(1 for p in all_papers if (p.get("track") or "A") == "A")
    n_b1 = sum(1 for p in all_papers if p.get("track") == "B1")
    n_b2 = sum(1 for p in all_papers if p.get("track") == "B2")
    n_b3 = sum(1 for p in all_papers if p.get("track") == "B3")
    n_classic = sum(1 for p in all_papers if p.get("_classic_seed") and _seed_label(p) == "经典必读")
    n_local_seed = sum(1 for p in all_papers if p.get("_classic_seed") and _seed_label(p) == "本地补充")
    n_obj1 = sum(1 for p in all_papers if "G1" in p.get("_objectives", []))
    n_obj2 = sum(1 for p in all_papers if "G2" in p.get("_objectives", []))
    n_obj3 = sum(1 for p in all_papers if "G3" in p.get("_objectives", []))
    n_obj4 = sum(1 for p in all_papers if "G4" in p.get("_objectives", []))
    n_highlight = sum(1 for p in all_papers if p.get("_score", 0) >= 10)
    print("\n" + "=" * 70)
    if top_only:
        print(f"共 {len(all_papers)} 篇（顶会/顶刊，{min_year} 年及以后 + 经典必读）")
    else:
        print(f"共得到 {len(all_papers)} 篇不重复论文（{min_year} 年及以后 + 经典必读）")
    print(f"  → 轨道 A (FL算法): {n_a} 篇 | B1 (FL系统): {n_b1} 篇 | B2 (默认关闭): {n_b2} 篇 | B3 (自治/自适应系统): {n_b3} 篇")
    print(f"  → G1 自主闭环聚合: {n_obj1} 篇 | G2 漂移/持续适应: {n_obj2} 篇 | G3 资源感知个性化: {n_obj3} 篇 | G4 自治/自适应系统: {n_obj4} 篇")
    print(f"  → ⭐ 重点论文(score≥10): {n_highlight} 篇 | 经典必读: {n_classic} 篇 | 本地补充: {n_local_seed} 篇 | 🆕 本次新增: {n_new} 篇")
    print("=" * 70)
    for j, p in enumerate(all_papers[:80], 1):
        venue = p.get("venue") or ""
        top = " [顶会/顶刊]" if (is_top_venue(venue) or is_infra_venue(venue) or is_autonomic_venue(venue)) else ""
        classic = f" [{_seed_label(p)}]" if p.get("_classic_seed") else ""
        if p.get("verified"):
            v = " [已确认顶会顶刊]"
        else:
            v = ""
        year = p.get("year") or "?"
        cite = p.get("citationCount")
        cite_str = f", 引用 {cite}" if cite is not None else ""
        tr = p.get("track") or "A"
        if tr == "B1":
            track_tag = "[B1]"
        elif tr == "B2":
            track_tag = "[B2]"
        elif tr == "B3":
            track_tag = "[B3]"
        else:
            track_tag = "[A]"
        obj_tag = " ".join(p.get("_objectives", []))
        obj_display = f" [{obj_tag}]" if obj_tag else ""
        new_flag = " 🆕" if p.get("_is_new") else ""
        star_flag = " ⭐" if p.get("_score", 0) >= 10 else ""
        print(f"\n{j}. {track_tag}{obj_display}{star_flag}{new_flag} {p.get('title', '')}{classic}{top}{v}")
        print(f"   作者: {', '.join((p.get('authors') or [])[:5])}{'...' if len(p.get('authors') or []) > 5 else ''}")
        print(f"   年份: {year}, 出处: {venue}{cite_str}")
        print(f"   链接: {p.get('url', '')}")
        if p.get("abstract"):
            ab = (p["abstract"] or "")[:200].replace("\n", " ")
            print(f"   摘要: {ab}...")

    # 写入 CSV
    if output_csv:
        out_path = Path(output_csv)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["标题", "作者", "年份", "出处", "引用数", "链接", "摘要", "是否顶会顶刊", "来源", "比对确认", "评分", "轨道", "核心目标", "领域", "新论文"])
            for p in all_papers:
                authors_str = "; ".join(p.get("authors") or [])
                src = _seed_source(p) if p.get("_classic_seed") else "S2"
                if p.get("_classic_seed"):
                    confirm = _seed_label(p)
                elif p.get("verified"):
                    confirm = "是（已确认顶会顶刊）"
                elif p.get("verified_note") == "已发表论文":
                    confirm = "已发表"
                else:
                    confirm = "否"
                tr = p.get("track") or "A"
                if tr == "B1":
                    track_label = "B1 (FL系统实现)"
                elif tr == "B2":
                    track_label = "B2 (分布式ML系统)"
                elif tr == "B3":
                    track_label = "B3 (自治/自适应系统)"
                else:
                    track_label = "A (FL算法)"
                obj_str = ", ".join(p.get("_objectives", []))
                is_new = "🆕" if p.get("_is_new") else ""
                w.writerow([
                    (p.get("title") or "").replace("\n", " "),
                    authors_str,
                    p.get("year") or "",
                    (p.get("venue") or "").replace("\n", " "),
                    p.get("citationCount") or "",
                    p.get("url") or "",
                    (p.get("abstract") or "").replace("\n", " ")[:1000],
                    _seed_label(p) if p.get("_classic_seed") else ("是" if (is_top_venue(p.get("venue") or "") or is_infra_venue(p.get("venue") or "") or is_autonomic_venue(p.get("venue") or "")) else "否"),
                    src,
                    confirm,
                    p.get("_score", ""),
                    track_label,
                    obj_str,
                    infer_domain(p),
                    is_new,
                ])
        print(f"\nCSV 已保存: {out_path.absolute()}")

    # 生成 HTML 报告（便于浏览器查看）
    if output_html and all_papers:
        html_path = write_html_report(all_papers, output_html, min_year)
        print(f"HTML 报告已保存: {html_path.absolute()}")
        try:
            import webbrowser
            webbrowser.open(html_path.as_uri())
        except Exception:
            pass

    if expand_citations and output_csv and all_papers:
        print("\n[Snowball] 从经典/高分论文出发扩展 citations + references...")
        expanded = expand_citations_from_papers(
            all_papers,
            existing_papers=all_papers,
            seed_limit=snowball_seed_limit,
            citations_per_seed=snowball_citations_per_seed,
            references_per_seed=snowball_references_per_seed,
            min_year=min_year,
        )
        citation_path = Path(output_csv).parent / "papers_search_citation_expanded.csv"
        write_csv_report(expanded, citation_path)
        print(f"[Snowball] 引用扩展候选已保存: {citation_path.absolute()}（{len(expanded)} 篇）")
        print("[Snowball] 注意：当前仓库只保留统一 HTML/CSV 主报告，引用扩展 CSV 默认不纳入 Git。")

    return all_papers


def bootstrap_intermediates_from_unified(base: Path) -> None:
    """Recreate ignored intermediate CSVs from the committed unified CSV if needed."""
    unified = base / "paper_search_report.csv"
    raw = base / "papers_search_results.csv"
    downloadable = base / "papers_search_results_downloadable.csv"
    if not unified.exists() or (raw.exists() and downloadable.exists()):
        return
    with unified.open(encoding="utf-8-sig", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("来源") == "TopVenue"]
    if not rows:
        return

    if not raw.exists():
        raw_fields = ["标题", "作者", "年份", "出处", "引用数", "链接", "摘要", "是否顶会顶刊", "来源", "比对确认", "评分", "轨道", "核心目标", "领域", "新论文"]
        with raw.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=raw_fields)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "标题": row.get("标题", ""),
                    "作者": row.get("作者", ""),
                    "年份": row.get("年份", ""),
                    "出处": row.get("出处或类别", ""),
                    "引用数": "",
                    "链接": row.get("论文页", ""),
                    "摘要": row.get("摘要", ""),
                    "是否顶会顶刊": "是",
                    "来源": "unified-bootstrap",
                    "比对确认": "",
                    "评分": row.get("评分", ""),
                    "轨道": row.get("轨道", ""),
                    "核心目标": row.get("核心目标", ""),
                    "领域": row.get("领域", ""),
                    "新论文": "",
                })

    if not downloadable.exists():
        fields = ["序号", "标题", "作者", "年份", "出处", "引用数", "评分", "轨道", "领域", "核心目标", "是否顶会顶刊", "摘要", "下载状态", "下载说明", "内容已检测", "本地PDF", "PDF直链", "正确论文页", "链接修正说明", "原始链接", "DOI", "OA状态"]
        with downloadable.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            for idx, row in enumerate(rows, start=1):
                writer.writerow({
                    "序号": str(idx),
                    "标题": row.get("标题", ""),
                    "作者": row.get("作者", ""),
                    "年份": row.get("年份", ""),
                    "出处": row.get("出处或类别", ""),
                    "引用数": "",
                    "评分": row.get("评分", ""),
                    "轨道": row.get("轨道", ""),
                    "领域": row.get("领域", ""),
                    "核心目标": row.get("核心目标", ""),
                    "是否顶会顶刊": "是",
                    "摘要": row.get("摘要", ""),
                    "下载状态": row.get("下载状态", ""),
                    "下载说明": "",
                    "内容已检测": row.get("内容已检测", ""),
                    "本地PDF": row.get("本地PDF", ""),
                    "PDF直链": row.get("PDF直链", ""),
                    "正确论文页": row.get("论文页", ""),
                    "链接修正说明": "from unified report",
                    "原始链接": row.get("论文页", ""),
                    "DOI": row.get("DOI", ""),
                    "OA状态": "",
                })

def _cleanup_intermediates(base: Path) -> None:
    # Keep only the two final report files; all .py scripts are preserved by the glob below.
    keep_files = {
        "paper_search_report.csv",
        "paper_search_report.html",
    }
    # Also preserve any committed helper scripts (all .py files)
    keep_files.update({f.name for f in base.glob("*.py")})

    removed_files = []
    for child in sorted(base.iterdir()):
        if child.is_file() and child.suffix in {".csv", ".html"} and child.name not in keep_files:
            try:
                child.unlink()
                removed_files.append(child.name)
            except OSError:
                pass
        elif child.is_dir() and child.name == "local_pdfs_not_in_search":
            try:
                shutil.rmtree(child)
                removed_files.append(child.name + "/")
            except OSError:
                pass
    if removed_files:
        print(f"[清理] 已删除中间文件：{', '.join(removed_files)}")


def _clean(path: Path) -> bool:
    """Remove a single file or directory tree. Returns True if something was removed."""
    try:
        if path.is_file():
            path.unlink()
            return True
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
            return path.exists() is False
    except Exception:
        pass
    return False


def clean_intermediates(base: Path, *, aggressive: bool = True) -> list[str]:
    """Delete every intermediate file that can affect run results.

    Parameters
    ----------
    base : Path
        Paper-search script directory.
    aggressive : bool,
        When True (default) also wipe the arXiv PDF sub-folder so the next
        arXiv crawl starts fresh.  Set to False when only refreshing reports
        (``--reports-only``) so existing downloaded PDFs are preserved.

    Removes stale crawler CSVs, HTML intermediates, and any prior-run OCR
    outputs (unless *aggressive* is False).  Does **not** touch the S2 cache
    (``.s2_cache/``) or the seen-papers tracking file (``.seen_papers.json``);
    those survive across runs so the crawler can still identify new papers.
    """
    removed: list[str] = []

    if aggressive:
        # ── Full clean (default): wipe everything that might be stale ────────
        # Includes crawler intermediates, report intermediates, arXiv PDF folder
        wipe_candidates = [
            "papers_search_results.csv",
            "papers_search_results.html",
            "papers_search_results_downloadable.csv",
            "arxiv_latest_half_year.csv",
            "arxiv_latest_half_year.html",
            "local_pdf_reconciliation.html",
            "local_pdf_reconciliation.csv",
            "local_pdfs_not_in_search.csv",
            "local_pdfs_not_in_search.html",
        ]
        for name in wipe_candidates:
            p = base / name
            if _clean(p):
                removed.append(name)

        # ── arXiv PDF sub-folder (fresh crawl starts empty) ──────────────────
        repo2 = base.parent
    if aggressive:
        repo = base.parent
        from utils.paths import find_pdf_root
        pdf_root = find_pdf_root(repo)
        arxiv_pdf_dir = pdf_root / "arxiv_latest_papers"
        if arxiv_pdf_dir.exists():
            _clean(arxiv_pdf_dir)
            removed.append("PHD-Buyya/arxiv_latest_papers/")

    # ── Discovery-pool / citation-expanded CSVs ────────────────────────────
    # Only in aggressive mode; harmless to scan always but skip to avoid
    # accidentally deleting useful data reports.

    if removed:
        print(f"[clean] Removed {len(removed)} intermediate items: {', '.join(removed)}")
    return removed


def build_reports(run_arxiv: bool = True, rename_arxiv: bool = True, *, enable_multipaper: bool = True) -> None:
    """Generate the unified user-facing report from crawler intermediates."""
    base = Path(__file__).resolve().parents[1]
    print("\n[报告流程] 目标：生成 paper_search_report.html / paper_search_report.csv")

    if run_arxiv:
        try:
            from crawlers import arxiv as arxiv_latest_crawler

            print("[报告流程 1/5] 同步 arXiv 最新论文和 PDF...")
            arxiv_latest_crawler.main()
        except Exception as exc:
            print(f"[报告流程 1/5] arXiv 同步失败，保留已有中间文件：{exc}")
    else:
        print("[报告流程 1/5] 跳过 arXiv；保留已有中间文件")

    bootstrap_intermediates_from_unified(base)

    report_args = SimpleNamespace(
        input=str(base / "papers_search_results.csv"),
        output=str(base / "papers_search_results.html"),
        output_csv=str(base / "papers_search_results_downloadable.csv"),
    )

    from reporting.enrichment import build as build_downloadable_report
    from reporting.missing import main as build_missing_downloads_report
    from reporting.unified import build as build_unified_report
    from utils.reconcile import reconcile_local_pdfs

    print("[报告流程 2/5] 生成顶会顶刊中间表...")
    try:
        build_downloadable_report(report_args)
    except FileNotFoundError as exc:
        print(f"[警告] 跳过中间表生成（{exc}）—— 可能是 --reports-only 尚无爬取结果")

    print("[报告流程 3/5] 扫描本地 PDF 文件夹并回填下载状态...")
    try:
        local_stats = reconcile_local_pdfs(write_reports=False, enable_multipaper=enable_multipaper)
        print(f"         索引 {local_stats.get('local_indexed', 0)} 个 PDF，"
              f"匹配 {local_stats.get('buyya_matched', 0)} 篇至报告条目")
    except FileNotFoundError as exc:
        print(f"[警告] 跳过本地扫描（{exc}）—— --reports-only 尚无爬取结果")
        local_stats = {"local_indexed": 0, "buyya_matched": 0}

    # Rebuild after local reconciliation so the all-papers HTML points at the
    # newly discovered local PDFs as well.
    try:
        build_downloadable_report(report_args)
    except FileNotFoundError:
        print("[警告] 无法重建中间表（papers_search_results.csv 缺失），跳过")

    print("[报告流程 4/5] 生成未下载中间表...")
    try:
        build_missing_downloads_report([])
    except FileNotFoundError:
        print("[警告] 无法生成缺失论文列表（依赖中间表），跳过")

    print("[报告流程 5/5] 合并为单一 HTML/CSV...")
    try:
        html_path, csv_path, count = build_unified_report(base)
        print(f"[报告流程] 完成：{html_path.name} / {csv_path.name}（{count} rows）")
    except FileNotFoundError as exc:
        print(f"[错误] 无法生成统一报告（{exc}）。"
              f"可尝试: python3 paper_search_crawler.py  （完整爬取流程）")
        return

    # Optional: rename arXiv PDFs that were latest downloaded
    if rename_arxiv and run_arxiv:
        try:
            from pdf_ops.rename import main as rename_arxiv_pdfs
            print("[报告流程] 重命名 arXiv 最新 PDF（按报告标题）...")
            rename_arxiv_pdfs([])
        except Exception as exc:
            print(f"[报告流程] arXiv PDF 重命名跳过：{exc}")

    # PDF 精确去重（报告生成后执行，不影响报告数据）
    from pdf_ops.dedup import dedup_pdfs
    from utils.paths import find_pdf_root
    pdf_root = find_pdf_root(base.parent)
    dup_stats = dedup_pdfs(pdf_root, dry_run=False)
    if dup_stats["dup_groups"]:
        print(f"[去重] 删除 {dup_stats['deleted']} 个副本"
              f"（{dup_stats['dup_groups']} 组），剩余 {dup_stats['total_after']} 个 PDF")
    else:
        print(f"[去重] 无重复，PHD-Buyya 共 {dup_stats['total_after']} 个 PDF")

    # Final clean-up: remove everything except the two committed report files
    # and any helper scripts.
    _cleanup_intermediates(base)


def main(argv: list[str] | None = None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="Search papers and generate the unified paper report.")
    parser.add_argument("--reports-only", action="store_true", help="only regenerate the unified report from existing CSV/local PDFs")
    parser.add_argument("--skip-arxiv", action="store_true", default=os.getenv("PAPER_SEARCH_SKIP_ARXIV") == "1", help="skip arXiv latest crawler in the final report flow")
    parser.add_argument("--no-rename-arxiv", action="store_true", help="skip renaming arXiv PDFs to standard format after crawl")
    parser.add_argument("--skip-post", action="store_true", default=os.getenv("PAPER_SEARCH_SKIP_POST") == "1", help="skip the final report post-processing flow")
    parser.add_argument("--no-clean", action="store_true", help="skip the automatic intermediate-file cleanup before running")
    parser.add_argument("--clean", action="store_true", help="full cold start: clear intermediates AND S2 cache / seen-papers tracking")
    parser.add_argument("--no-multipaper", action="store_true", help="skip 合订本/多论文 PDF 的反向匹配（默认开启）")
    args = parser.parse_args(argv)

    base = Path(__file__).resolve().parents[1]

    if args.clean:
        # Full cold start: intermediates + arXiv PDF folder + S2 cache + seen-papers
        clean_intermediates(base, aggressive=True)
        _cleanup_intermediates(base)
        cache_dir = base / ".s2_cache"
        if _clean(cache_dir):
            print("[clean] Removed .s2_cache/")
        seen_file = base / ".seen_papers.json"
        if _clean(seen_file):
            print("[clean] Removed .seen_papers.json")
    elif not args.no_clean:
        # Default: full aggressive clean.
        # --reports-only overrides to light clean (keeps S2 crawl CSV + arXiv PDFs).
        aggressive = not args.reports_only
        clean_intermediates(base, aggressive=aggressive)

    if args.reports_only:
        build_reports(run_arxiv=not args.skip_arxiv, rename_arxiv=not args.no_rename_arxiv,
                      enable_multipaper=not args.no_multipaper)
        return

    out_base = "papers_search_results"
    run_search(
        queries=DEFAULT_QUERIES,
        min_year=DEFAULT_MIN_YEAR,
        max_per_query=300,
        use_s2=True,
        output_csv=out_base + ".csv",
        output_html=out_base + ".html",
        top_only=True,
        verify=False,
        verify_limit=5,
        expand_citations=False,
        snowball_seed_limit=30,
        snowball_citations_per_seed=50,
        snowball_references_per_seed=30,
    )
    if not args.skip_post:
        build_reports(run_arxiv=not args.skip_arxiv, rename_arxiv=not args.no_rename_arxiv,
                      enable_multipaper=not args.no_multipaper)


if __name__ == "__main__":
    print("正在启动论文搜索/报告流程...", flush=True)
    if requests is None:
        print("错误: 未安装 requests。请运行: pip install requests", flush=True)
        if sys.platform == "win32":
            input("按回车键退出...")
        sys.exit(1)
    try:
        main()
    except Exception as e:
        print(f"\n错误: {e}", flush=True)
        import traceback
        traceback.print_exc()
        if sys.platform == "win32":
            input("\n按回车键退出...")
        sys.exit(1)
    print("\n完成。", flush=True)
