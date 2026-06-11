import json
from typing import Any

from app.services.agent.schemas import AgentModMatch
from app.services.llm_client import create_llm_client
from app.utils.ids import positive_integer_id
from app.utils.json import json_object_from_text


async def validate_matches_with_llm(
    *,
    query: str,
    matches: list[AgentModMatch],
    provider: str,
    api_key: str,
    base_url: str,
    model: str,
    query_plan: dict[str, Any] | None = None,
) -> list[AgentModMatch]:
    """调用 LLM 对候选 Mod 做语义相关性重排和过滤。"""
    if not matches:
        return matches
    client = create_llm_client(provider=provider, api_key=api_key, base_url=base_url)
    lines = [
        "你是 Mod 语义相关性重排器，作用类似 cross-encoder。",
        "SQL 阶段已经完成 game/game_domain/category/source/adult_content/time/sort 等结构化硬过滤。",
        "你的任务只判断“用户问题”和“候选 Mod”在语义需求上是否相关，不要重复否决结构化硬约束。",
        "仅输出 JSON：{\"items\":[{\"id\":int,\"score\":0.0,\"reason\":\"简短原因\"}]}。",
        "规则：",
        "1) score 范围 0~1，表示语义相关性",
        "2) 关注标题、分类、摘要、作者、指标与用户真实需求的匹配度",
        "3) 用户只问排序或泛查询时，不要因为标题不含关键词而降到 0",
        "4) 明显不满足语义需求的条目给 0~0.39；弱相关 0.4~0.59；相关 0.6~0.79；强相关 0.8~1",
        "5) 如果都不相关，items 返回空数组",
        "",
        f"用户问题：{query}",
        f"结构化查询词槽：{json.dumps(query_plan or {}, ensure_ascii=False)}",
        "候选：",
    ]
    for idx, item in enumerate(matches, start=1):
        lines.append(
            f"{idx}. id={item.id}; title={item.title}; game={item.game}; game_domain={item.game_domain or 'unknown'}; "
            f"category={item.category or 'unknown'}; source={item.source}; adult_content={item.adult_content}; "
            f"downloads={item.downloads}; endorsements={item.endorsements}; likes={item.likes}; "
            f"author={item.author or 'unknown'}; updated_at_remote={item.updated_at_remote or 'unknown'}; "
            f"translated_summary={(item.translated_summary or '')[:400]}; original_summary={(item.original_summary or '')[:400]}"
        )
    raw = await client.chat("\n".join(lines), model=model, max_tokens=200)
    data = json_object_from_text(raw)
    if not isinstance(data, dict):
        return matches
    scored_raw = data.get("items")
    if not isinstance(scored_raw, list):
        return matches
    score_by_id: dict[int, float] = {}
    for item in scored_raw:
        if not isinstance(item, dict):
            continue
        raw_id = item.get("id")
        item_id = positive_integer_id(raw_id, allow_string=True)
        if item_id is None:
            continue
        try:
            score = float(item.get("score"))
        except (TypeError, ValueError):
            continue
        score_by_id[item_id] = max(0.0, min(1.0, score))
    if not score_by_id:
        return matches
    reranked = [item for item in matches if score_by_id.get(item.id, 0.0) >= 0.4]
    if not reranked:
        return matches
    reranked.sort(key=lambda item: (score_by_id.get(item.id, 0.0), item.score), reverse=True)
    return reranked
