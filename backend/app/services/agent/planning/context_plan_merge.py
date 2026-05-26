
from app.services.agent.context.context_inference import should_inherit_context_keywords
from app.services.agent.semantic_search import distinctive_query_terms


def merge_context_query_plan(raw_plan: dict | None, context_plan: dict | None) -> dict | None:
    """Use contextual planning only for slots the current turn did not fill."""
    if not isinstance(context_plan, dict):
        return raw_plan
    merged = dict(raw_plan or {})
    if not merged.get("evidence_id") and context_plan.get("evidence_id"):
        merged["evidence_id"] = context_plan["evidence_id"]
    for key, value in context_plan.items():
        if str(key).startswith("_agent_"):
            merged[key] = value
    if _should_replace_keywords_with_context(merged.get("keywords"), context_plan.get("keywords")):
        merged["keywords"] = context_plan["keywords"]
    for key in [
        "games",
        "game_domains",
        "categories",
        "tags",
        "summary_languages",
        "excluded_summary_languages",
        "requirement_terms",
        "compatibility_terms",
        "sources",
    ]:
        if not merged.get(key) and context_plan.get(key):
            merged[key] = context_plan[key]
    if not merged.get("exact_title") and context_plan.get("exact_title"):
        merged["exact_title"] = context_plan["exact_title"]
    if not merged.get("version") and context_plan.get("version"):
        merged["version"] = context_plan["version"]
    for key in ["updated_after", "updated_before", "published_after", "published_before", "created_after", "created_before"]:
        if not merged.get(key) and context_plan.get(key):
            merged[key] = context_plan[key]
    if not merged.get("external_id") and context_plan.get("external_id"):
        merged["external_id"] = context_plan["external_id"]
    if not merged.get("source_url") and context_plan.get("source_url"):
        merged["source_url"] = context_plan["source_url"]
    if merged.get("adult_content") is None and context_plan.get("adult_content") is not None:
        merged["adult_content"] = context_plan["adult_content"]
    if not merged.get("sort_field") and context_plan.get("sort_field"):
        merged["sort_field"] = context_plan["sort_field"]
    if not merged.get("sort_order") and context_plan.get("sort_order"):
        merged["sort_order"] = context_plan["sort_order"]
    if context_plan.get("exclude_titles"):
        merged["exclude_titles"] = context_plan["exclude_titles"]
    if context_plan.get("keyword_match_mode"):
        merged["keyword_match_mode"] = context_plan["keyword_match_mode"]
    if context_plan.get("excluded_sources"):
        merged["excluded_sources"] = context_plan["excluded_sources"]
    return merged


def merge_llm_context_query_plan(raw_plan: dict | None, context_plan: dict | None) -> dict | None:
    """Merge only explicit inherited context into an LLM plan.

    Current-turn fallback parsing can be useful when LLM planning is unavailable,
    but it should not repair or override an LLM plan. For LLM output, only carry
    internal context metadata and slots that were explicitly inherited from
    previous context.
    """
    if not isinstance(context_plan, dict):
        return raw_plan
    merged = dict(raw_plan or {})
    if not merged.get("evidence_id") and context_plan.get("evidence_id"):
        merged["evidence_id"] = context_plan["evidence_id"]
    for key, value in context_plan.items():
        if str(key).startswith("_agent_"):
            merged[key] = value
    _merge_result_reference_constraints(merged, context_plan)
    context_signal = context_plan.get("_agent_context_signal")
    if not isinstance(context_signal, dict) or not context_signal.get("inherited") or context_signal.get("topic_shift"):
        return merged
    for key in ["games", "game_domains", "categories", "sources"]:
        if not merged.get(key) and context_plan.get(key):
            merged[key] = context_plan[key]
    if merged.get("adult_content") is None and context_plan.get("adult_content") is not None:
        merged["adult_content"] = context_plan["adult_content"]
    if not merged.get("sort_field") and context_plan.get("sort_field"):
        merged["sort_field"] = context_plan["sort_field"]
    if not merged.get("sort_order") and context_plan.get("sort_order"):
        merged["sort_order"] = context_plan["sort_order"]
    return merged


def _merge_result_reference_constraints(merged: dict, context_plan: dict) -> None:
    signal = context_plan.get("_agent_result_reference_signal")
    if not isinstance(signal, dict) or not signal.get("applied"):
        return
    fields = {str(field).strip() for field in (signal.get("fields") or []) if str(field).strip()}
    if "exact_title" in fields and context_plan.get("exact_title"):
        merged["exact_title"] = context_plan["exact_title"]
        if context_plan.get("keywords"):
            merged["keywords"] = context_plan["keywords"]
    if "exclude_titles" in fields and context_plan.get("exclude_titles"):
        merged["exclude_titles"] = context_plan["exclude_titles"]
    if "keyword_match_mode" in fields and context_plan.get("keyword_match_mode"):
        merged["keyword_match_mode"] = context_plan["keyword_match_mode"]
        if context_plan.get("keywords"):
            merged["keywords"] = context_plan["keywords"]


def _should_replace_keywords_with_context(raw_keywords: object, context_keywords: object) -> bool:
    if not context_keywords:
        return False
    raw_values = [str(value).strip() for value in (raw_keywords or []) if str(value).strip()]
    context_values = [str(value).strip() for value in (context_keywords or []) if str(value).strip()]
    if not context_values:
        return False
    if not raw_values:
        return True
    return should_inherit_context_keywords(" ".join(raw_values), raw_values, context_values) or not distinctive_query_terms(
        " ".join(raw_values)
    )
