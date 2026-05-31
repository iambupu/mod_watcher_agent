from typing import Any

QUERY_PLAN_EVIDENCE_FIELDS = [
    "keywords",
    "games",
    "game_domains",
    "sources",
    "categories",
    "category_hints",
    "tags",
    "adult_content",
    "has_thumbnail",
    "summary_languages",
    "excluded_summary_languages",
    "requirement_terms",
    "compatibility_terms",
    "author",
    "sort_field",
    "sort_order",
    "exact_title",
    "version",
    "external_id",
    "source_url",
]


def active_query_plan_fields(query_plan: dict[str, Any]) -> list[str]:
    """返回当前查询计划中实际生效的字段，用于 evidence 和审计展示。"""
    return [key for key in QUERY_PLAN_EVIDENCE_FIELDS if query_plan.get(key) not in (None, "", [])]


def append_retrieval_evidence(
    evidence: list[dict[str, object]],
    *,
    stage: str,
    tool: str,
    status: str,
    count: int,
    reason: str | None = None,
    fields: list[str] | None = None,
    evidence_id: str = "",
    fragment_prefix: str = "r_exec",
) -> None:
    """追加标准检索 evidence，避免各工具重复拼装同一结构。"""
    item: dict[str, object] = {
        "fragment_id": f"{fragment_prefix}_{len(evidence) + 1}",
        "stage": stage,
        "tool": tool,
        "status": status,
        "count": count,
    }
    if evidence_id:
        item["evidence_id"] = evidence_id
    if reason:
        item["reason"] = reason
    if fields:
        item["fields"] = fields
    evidence.append(item)
