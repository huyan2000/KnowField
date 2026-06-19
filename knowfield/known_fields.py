from __future__ import annotations

KNOWN_FIELDS: dict[str, dict[str, object]] = {
    "边缘计算": {
        "field_name": "边缘计算",
        "slug": "edge-computing",
        "aliases": [
            "edge computing",
            "mobile edge computing",
            "fog computing",
            "cloud-edge collaboration",
            "edge intelligence",
        ],
        "description": "边缘计算把一部分计算放到更靠近用户、设备和数据产生地的位置，而不是把所有数据都送到远端集中处理。",
        "why_it_matters": "它适合需要低延迟、少传输、本地响应或数据就近处理的场景，例如工业设备、车联网、视频分析和物联网系统。",
        "seed_keywords": {
            "plain_language": [
                "边缘计算 入门",
                "edge computing explained",
                "what is edge computing",
            ],
            "academic": [
                "edge computing survey",
                "mobile edge computing survey",
                "edge computing task offloading",
                "edge computing resource allocation",
                "cloud edge collaboration",
                "edge intelligence survey",
            ],
            "engineering": [
                "edge computing platform",
                "edge model deployment",
                "edge computing system",
                "IoT edge gateway",
            ],
            "practice": [
                "edge computing use cases",
                "industrial IoT edge computing",
                "edge computing challenges",
            ],
        },
        "starter_questions": [
            "边缘计算主要解决什么问题？",
            "它和云计算、物联网、雾计算有什么区别？",
            "哪些场景真的需要边缘计算？",
            "哪些方向已经比较成熟？",
            "哪些问题仍然没有稳定答案？",
        ],
        "timeline": [
            "集中式云服务让远端计算变得普及。",
            "移动设备、传感器和摄像头开始在本地产生大量数据。",
            "延迟、带宽、可靠性和数据本地性成为实际约束。",
            "边缘计算开始把部分任务放到设备附近执行。",
            "后续重点逐渐转向云、边缘节点和终端设备之间的协同。",
        ],
        "hot_topics": [
            "云边端协同",
            "任务卸载",
            "资源调度",
            "边缘模型部署",
            "隐私保护的分布式学习",
            "边缘安全与可靠性",
        ],
        "solved_problems": [
            "为什么要把部分计算放到更靠近设备的位置，这个基本动机已经比较清楚。",
            "缓存、网关、本地监控和预处理等模式已经有较多实践。",
            "云、边缘节点和终端设备的分层架构已经是常见解释方式。",
        ],
        "open_problems": [
            "边缘节点的硬件能力、网络条件和运行环境差异很大。",
            "一个任务应该放在本地、边缘还是远端执行，通常要根据场景动态判断。",
            "大量分散节点的运维、安全和故障处理比集中环境更复杂。",
            "在资源有限的边缘侧部署较大的模型仍然有成本和性能压力。",
        ],
        "learning_path": [
            "先理解客户端、服务器、网络延迟和带宽。",
            "再理解云计算为什么采用集中式资源池。",
            "比较本地处理、边缘处理和远端处理的差异。",
            "阅读一篇边缘计算综述，建立子方向地图。",
            "选择任务卸载、资源调度或边缘模型部署中的一个小方向继续深入。",
        ],
        "starter_projects": [
            "测量本地计算和远端请求的耗时差异。",
            "在本地机器上运行一个小服务，并从另一台设备访问它。",
            "写一个简单规则：根据网络延迟选择本地执行或远端执行。",
            "整理 5 篇边缘计算综述或论文，记录它们反复提到的问题。",
        ],
        "sources": [
            "Use collected paper links and introductory materials to verify this report.",
        ],
    },
    "推理框架": {
        "field_name": "推理框架",
        "slug": "inference-framework",
        "aliases": [
            "model serving",
            "large model serving",
            "LLM inference serving",
            "inference serving system",
            "LLM serving system",
            "serving system",
        ],
        "description": "推理框架负责把训练好的模型稳定、高效地运行起来，并对外提供可调用的服务。",
        "why_it_matters": "模型真正被用户使用时，瓶颈往往不只是模型效果，还包括延迟、吞吐、成本、显存、并发和稳定性。",
        "seed_keywords": {
            "plain_language": [
                "模型推理框架 入门",
                "inference engine explained",
                "model serving explained",
            ],
            "academic": [
                "large model serving survey",
                "inference serving system",
                "LLM serving system",
                "LLM inference serving",
                "model serving system scheduling",
                "KV cache inference serving",
                "continuous batching inference",
                "speculative decoding inference",
            ],
            "engineering": [
                "inference engine",
                "model serving framework",
                "low latency inference",
                "high throughput serving",
            ],
            "practice": [
                "model serving challenges",
                "inference optimization",
                "serving benchmark",
            ],
        },
        "starter_questions": [
            "推理框架主要解决什么问题？",
            "为什么模型部署后还需要专门的推理系统？",
            "延迟、吞吐、显存和成本之间有什么取舍？",
            "当前推理系统主要在优化哪些环节？",
        ],
        "hot_topics": [
            "请求调度",
            "批处理",
            "缓存管理",
            "预填充和解码分离",
            "量化",
            "推理加速",
        ],
        "open_problems": [
            "不同请求长度和并发模式会让资源调度变复杂。",
            "降低延迟和提高吞吐之间经常存在取舍。",
            "模型变大后，显存和通信成本会成为核心瓶颈。",
        ],
    },
    "训练框架": {
        "field_name": "训练框架",
        "slug": "training-framework",
        "aliases": [
            "training framework",
            "distributed training",
            "large model training",
            "training system",
        ],
        "description": "训练框架负责把模型训练过程组织起来，让数据、模型、优化器和硬件资源能够协同工作。",
        "why_it_matters": "当模型、数据和硬件规模变大后，训练不再只是写一个算法，还需要解决并行、通信、容错、调度和成本问题。",
        "seed_keywords": {
            "plain_language": [
                "分布式训练 入门",
                "large model training explained",
                "training system explained",
            ],
            "academic": [
                "distributed training survey",
                "large model training system",
                "data parallelism model parallelism training",
                "pipeline parallelism training",
                "optimizer state sharding",
                "distributed checkpointing",
            ],
            "engineering": [
                "distributed training framework",
                "training infrastructure",
                "GPU cluster training",
                "fault tolerant training",
            ],
            "practice": [
                "training system challenges",
                "large scale training cost",
                "distributed training benchmark",
            ],
        },
        "starter_questions": [
            "训练框架主要解决什么问题？",
            "为什么单机训练不够用后需要分布式训练？",
            "数据并行、模型并行和流水线并行分别解决什么问题？",
            "训练系统的瓶颈通常来自计算、通信还是存储？",
        ],
        "hot_topics": [
            "数据并行",
            "模型并行",
            "流水线并行",
            "状态切分",
            "通信优化",
            "容错和检查点",
        ],
        "open_problems": [
            "更大规模训练会放大通信和同步成本。",
            "硬件利用率、稳定性和成本之间存在复杂取舍。",
            "训练失败恢复和长时间任务管理仍然是工程难点。",
        ],
    },
}


def get_known_field(topic: str) -> dict[str, object] | None:
    normalized = topic.strip().lower()
    for key, config in KNOWN_FIELDS.items():
        names = [key, str(config.get("field_name", ""))]
        names.extend(str(alias) for alias in config.get("aliases", []) if alias)
        if normalized in {name.strip().lower() for name in names if name.strip()}:
            return dict(config)
    return None
