from __future__ import annotations

FIELD_REPORT_SCHEMA: dict[str, object] = {
    "field_name": "",
    "plain_explanation": "",
    "why_it_matters": "",
    "core_questions": [],
    "timeline": [],
    "current_stage": "",
    "maturity_evidence": [],
    "hot_topics": [],
    "solved_problems": [],
    "open_problems": [],
    "key_players": {
        "companies": [],
        "universities_labs": [],
        "open_source_projects": [],
        "standards_organizations": [],
    },
    "representative_papers": [],
    "representative_projects": [],
    "learning_path": [],
    "starter_projects": [],
    "sources": [],
}


MATURITY_LEVELS: list[dict[str, str]] = [
    {
        "level": "L1",
        "name": "概念期",
        "description": "定义仍不稳定，更多是愿景、术语和早期探索。",
    },
    {
        "level": "L2",
        "name": "探索期",
        "description": "论文和原型开始增多，但任务、指标和方法还未收敛。",
    },
    {
        "level": "L3",
        "name": "成长期",
        "description": "出现综述、benchmark、开源项目和固定社区方向。",
    },
    {
        "level": "L4",
        "name": "落地期",
        "description": "公司产品、真实部署、工程优化和招聘需求明显增加。",
    },
    {
        "level": "L5",
        "name": "成熟期",
        "description": "基础设施和产业链较稳定，研究更多转向成本、安全、标准化和细分优化。",
    },
]
