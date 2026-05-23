from typing import Any

from app.services.agent.schemas import AgentModMatch


def _display_query(query: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return (query or "").split("[scope]", 1)[0].strip()


def build_response_cards(
    *,
    query: str,
    query_plan: dict[str, Any] | None,
    matches: list[AgentModMatch],
    next_steps: list[str] | None = None,
) -> dict[str, list[str]]:
    """构建后续流程需要的数据结构。"""
    plan = query_plan or {}
    visible_query = _display_query(query)
    filters: list[str] = []
    games = [str(v) for v in (plan.get("games") or []) if str(v).strip()]
    categories = [str(v) for v in (plan.get("categories") or []) if str(v).strip()]
    sources = [str(v) for v in (plan.get("sources") or []) if str(v).strip()]
    if games:
        filters.append(f"游戏：{', '.join(games[:3])}")
    category_markers = ["类型", "分类", "category", "cate", "风格", "画面", "服装", "动作", "任务", "mod type"]
    query_lower = visible_query.lower()
    should_show_categories = any(marker in query_lower for marker in category_markers)
    if categories and should_show_categories:
        filters.append(f"类型：{', '.join(categories[:3])}")
    if sources:
        filters.append(f"来源：{', '.join(sources[:3])}")
    adult = plan.get("adult_content")
    if isinstance(adult, bool):
        filters.append(f"内容分级：{'NSFW' if adult else 'SFW'}")
    sort_field = str(plan.get("sort_field") or "").strip()
    sort_order = str(plan.get("sort_order") or "desc").strip().lower()
    if sort_field:
        sort_labels = {
            "updated_at_remote": "最近更新",
            "first_seen_at": "最近收录",
            "created_at_remote": "创建时间",
            "published_at_remote": "发布时间",
            "downloads": "下载量",
            "unique_downloads": "唯一下载量",
            "endorsements": "点赞/背书",
            "views": "浏览量",
            "likes": "喜欢数",
            "relevance": "相关性",
        }
        sort_label = sort_labels.get(sort_field, sort_field)
        filters.append(f"排序：{sort_label} ({'升序' if sort_order == 'asc' else '降序'})")

    understanding = [f"我理解你想找：{visible_query or query}"]
    results = [f"找到 {len(matches)} 个候选，优先推荐前 {min(3, len(matches))} 个。"] if matches else ["当前没有命中结果。"]
    if matches:
        for idx, item in enumerate(matches[:3], start=1):
            results.append(f"{idx}. {item.title}（{item.source} / {item.game}）")
    next_step_items = next_steps or (
        ["你可以继续指定：游戏、来源、时间范围、下载量阈值，或让我展开某个 Mod 的详细解析。"]
        if matches
        else ["请补充游戏名、来源或分类后再试，例如：最近更新的 Stellar Blade 画面 Mod。"]
    )
    return {
        "understanding": understanding,
        "filters": filters,
        "results": results,
        "next_steps": next_step_items,
    }
