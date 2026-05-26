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
            reason = f"；{item.rank_reason}" if item.rank_reason else ""
            results.append(f"{idx}. {item.title}（{item.source} / {item.game}）{reason}")
    next_step_items = next_steps or (
        ["你可以继续指定：游戏、来源、时间范围、下载量阈值，或让我展开某个 Mod 的详细解析。"]
        if matches
        else ["请补充游戏名、来源或分类后再试，例如：最近更新的 Stellar Blade 画面 Mod。"]
    )
    analysis = _build_analysis_cards(visible_query=visible_query or query, plan=plan, filters=filters)
    evidence = _build_evidence_cards(matches=matches)
    conclusion = _build_conclusion_cards(matches=matches, next_steps=next_step_items)
    return {
        "analysis": analysis,
        "evidence": evidence,
        "conclusion": conclusion,
        "understanding": understanding,
        "filters": filters,
        "results": results,
        "next_steps": next_step_items,
    }


def build_status_response_cards(
    *,
    analysis: str,
    evidence: str,
    conclusion: str,
    understanding: str,
    result: str,
    next_step: str,
) -> dict[str, list[str]]:
    return _standard_cards(
        analysis=[analysis],
        evidence=[evidence],
        conclusion=[conclusion, next_step],
        understanding=[understanding],
        filters=[],
        results=[result],
        next_steps=[next_step],
    )


def build_detail_response_cards(
    *,
    title: str,
    source: str,
    game: str,
    generated: bool,
) -> dict[str, list[str]]:
    result = f"已{'生成' if generated else '提供'}该 Mod 的{'详细解析' if generated else '详细信息'}（{title}）。"
    next_step = (
        "你可以继续问：安装步骤、前置依赖、同类替代 Mod。"
        if generated
        else "你可以继续问：兼容性、安装风险、适合人群。"
    )
    filters = [f"来源：{source}", f"游戏：{game}"]
    return _standard_cards(
        analysis=[f"任务分析：详细解析 {title}", f"已应用约束：{'；'.join(filters)}"],
        evidence=[f"证据：已定位到 Mod：{title}。", f"来源覆盖：{source}", f"游戏覆盖：{game}"],
        conclusion=[f"结论：可以继续查看 {title} 的详情。", next_step],
        understanding=[f"你希望我详细解析：{title}"],
        filters=filters,
        results=[result],
        next_steps=[next_step],
    )


def _build_analysis_cards(*, visible_query: str, plan: dict[str, Any], filters: list[str]) -> list[str]:
    intent = str(plan.get("intent") or "search").strip()
    lines = [f"任务分析：{visible_query}"]
    if intent:
        lines.append(f"识别意图：{intent}")
    if filters:
        lines.append(f"已应用约束：{'；'.join(filters)}")
    return lines


def _build_evidence_cards(*, matches: list[AgentModMatch]) -> list[str]:
    if not matches:
        return ["证据：当前检索没有返回候选 Mod。"]
    sources = sorted({str(item.source).strip() for item in matches if str(item.source).strip()})
    games = sorted({str(item.game).strip() for item in matches if str(item.game).strip()})
    lines = [f"证据：检索返回 {len(matches)} 个候选。"]
    if sources:
        lines.append(f"来源覆盖：{', '.join(sources[:3])}")
    if games:
        lines.append(f"游戏覆盖：{', '.join(games[:3])}")
    top_reasons = [str(item.rank_reason).strip() for item in matches[:3] if str(item.rank_reason or "").strip()]
    if top_reasons:
        lines.append(f"排序依据：{'；'.join(top_reasons)}")
    return lines


def _build_conclusion_cards(*, matches: list[AgentModMatch], next_steps: list[str]) -> list[str]:
    if matches:
        return [f"结论：优先查看前 {min(3, len(matches))} 个候选。", *next_steps[:2]]
    return ["结论：当前证据不足以给出可靠候选。", *next_steps[:2]]


def _standard_cards(
    *,
    analysis: list[str],
    evidence: list[str],
    conclusion: list[str],
    understanding: list[str],
    filters: list[str],
    results: list[str],
    next_steps: list[str],
) -> dict[str, list[str]]:
    return {
        "analysis": analysis,
        "evidence": evidence,
        "conclusion": conclusion,
        "understanding": understanding,
        "filters": filters,
        "results": results,
        "next_steps": next_steps,
    }
