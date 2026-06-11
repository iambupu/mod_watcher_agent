# 中文注释：规范化 Agent 查询计划、槽位约束和语义信号。

from app.services.agent.semantic_search import semantic_domains_for_anchors, semantic_query


def extract_semantic_anchors(query: str, keywords: list[str] | None = None) -> list[str]:
    text = " ".join([str(query or ""), *[str(value) for value in (keywords or []) if str(value).strip()]])
    return semantic_query(text).anchors


def anchor_domains(anchors: list[str]) -> list[str]:
    return semantic_domains_for_anchors(anchors)
