import re
from typing import Any

from app.models.mod import Mod
from app.services.agent.schemas import AgentModMatch
from app.services.agent.semantic_search import strip_scope


def display_query(query: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return strip_scope(query)


def match_from_mod(mod: Mod, score: int, summary_by_mod: dict[int, str]) -> AgentModMatch:
    return AgentModMatch(
        id=mod.id or 0,
        title=mod.title,
        translated_title_zh=mod.translated_title_zh,
        source=mod.source,
        game=mod.game,
        game_domain=mod.game_domain,
        category=mod.category,
        author=mod.author,
        version=mod.version,
        url=mod.url,
        updated_at_remote=mod.updated_at_remote,
        downloads=mod.downloads,
        endorsements=mod.endorsements,
        likes=mod.likes,
        adult_content=mod.adult_content,
        score=score,
        original_summary=mod.original_summary,
        translated_summary=summary_by_mod.get(mod.id or 0),
    )


def build_response_cards(
    *,
    query: str,
    query_plan: dict[str, Any] | None,
    matches: list[AgentModMatch],
    next_steps: list[str] | None = None,
) -> dict[str, list[str]]:
    """构建后续流程需要的数据结构。"""
    plan = query_plan or {}
    visible_query = display_query(query)
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
    judge_summary = plan.get("_agent_candidate_semantic_judge") if isinstance(plan.get("_agent_candidate_semantic_judge"), dict) else {}
    results = [f"找到 {len(matches)} 个候选，优先推荐前 {min(3, len(matches))} 个。"] if matches else ["当前没有命中结果。"]
    if matches:
        for idx, item in enumerate(matches[:3], start=1):
            results.append(_format_result_line(idx, item))
    next_step_items = _clean_next_steps(next_steps) or _default_next_steps(
        matches=matches,
        games=games,
        sources=sources,
        categories=categories,
    )
    analysis = _build_analysis_cards(visible_query=visible_query or query, plan=plan, filters=filters)
    evidence = _build_evidence_cards(matches=matches, judge_summary=judge_summary)
    conclusion = _build_conclusion_cards(matches=matches)
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
        conclusion=[conclusion],
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
    next_step = "这个 Mod 有哪些安装风险和前置依赖？" if generated else "这个 Mod 适合我当前的游戏版本吗？"
    filters = [f"来源：{source}", f"游戏：{game}"]
    return _standard_cards(
        analysis=[f"任务分析：详细解析 {title}", f"已应用约束：{'；'.join(filters)}"],
        evidence=[f"证据：已定位到 Mod：{title}。", f"来源覆盖：{source}", f"游戏覆盖：{game}"],
        conclusion=[f"结论：可以继续查看 {title} 的详情。"],
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


def _format_result_line(index: int, item: AgentModMatch) -> str:
    summary = _compact_text(item.translated_summary or item.original_summary or "", limit=180)
    reason = _compact_text(item.rank_reason or "", limit=120)
    parts = [f"{index}. {item.title}（{item.source} / {item.game}）"]
    if summary:
        parts.append(f"说明：{summary}")
    if reason:
        parts.append(f"匹配：{reason}")
    return "；".join(parts)


def _compact_text(value: str, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _build_evidence_cards(*, matches: list[AgentModMatch], judge_summary: dict[str, Any] | None = None) -> list[str]:
    if not matches:
        return ["证据：当前检索没有返回候选 Mod。"]
    sources = sorted({str(item.source).strip() for item in matches if str(item.source).strip()})
    games = sorted({str(item.game).strip() for item in matches if str(item.game).strip()})
    lines = [f"证据：检索返回 {len(matches)} 个候选。"]
    judge = judge_summary or {}
    if judge:
        # response card 只展示 judge 摘要；具体排序仍来自已经裁判过的 matches，避免前端再做二次决策。
        mode = "LLM 语义裁判" if judge.get("used_llm") else "语义裁判降级"
        lines.append(f"候选裁判：{mode}（{judge.get('status') or 'unknown'}）")
        group_lines = _format_judge_group_lines(judge)
        lines.extend(group_lines)
    if sources:
        lines.append(f"来源覆盖：{', '.join(sources[:3])}")
    if games:
        lines.append(f"游戏覆盖：{', '.join(games[:3])}")
    top_reasons = [str(item.rank_reason).strip() for item in matches[:3] if str(item.rank_reason or "").strip()]
    if top_reasons:
        lines.append(f"排序依据：{'；'.join(top_reasons)}")
    return lines


def _format_judge_group_lines(judge: dict[str, Any]) -> list[str]:
    groups = judge.get("groups") if isinstance(judge.get("groups"), list) else []
    lines: list[str] = []
    for group in groups[:4]:
        if not isinstance(group, dict):
            continue
        label = str(group.get("label") or group.get("name") or "").strip()
        candidate_ids = group.get("candidate_ids") if isinstance(group.get("candidate_ids"), list) else []
        if label and candidate_ids:
            lines.append(f"语义分组：{label}（{len(candidate_ids)} 个）")
    gaps = judge.get("gaps") if isinstance(judge.get("gaps"), list) else []
    if gaps:
        lines.append(f"证据缺口：{'; '.join(str(item) for item in gaps[:2])}")
    return lines


def _build_conclusion_cards(*, matches: list[AgentModMatch]) -> list[str]:
    if matches:
        return [f"结论：优先查看前 {min(3, len(matches))} 个候选。"]
    return ["结论：当前证据不足以给出可靠候选。"]


def _default_next_steps(
    *,
    matches: list[AgentModMatch],
    games: list[str],
    sources: list[str],
    categories: list[str],
) -> list[str]:
    if matches:
        first = matches[0]
        steps = [
            f"请详细解析 {first.title}",
            "这些结果里哪个安装风险最低？",
        ]
        if sources:
            steps.append(f"只看 {sources[0]} 来源的结果")
        elif games:
            steps.append(f"只看 {games[0]} 的结果")
        else:
            steps.append("按最近更新重新排序")
        return steps[:3]
    return [_no_match_next_step(games=games, sources=sources, categories=categories)]


def _no_match_next_step(*, games: list[str], sources: list[str], categories: list[str]) -> str:
    hints = []
    if games:
        hints.append(f"保留 {games[0]}")
    if sources:
        hints.append(f"继续查 {sources[0]} 来源")
    if categories:
        hints.append(f"按 {categories[0]} 类型继续找")
    if hints:
        return f"{'，'.join(hints)}，但放宽关键词再查一次"
    return "换成全部来源，再用更宽的关键词查一次"


def _clean_next_steps(next_steps: list[str] | None) -> list[str]:
    cleaned: list[str] = []
    for item in next_steps or []:
        value = re.sub(r"\s+", " ", str(item or "").strip())
        if not value or _looks_like_broken_structured_output(value):
            continue
        if value not in cleaned:
            cleaned.append(value[:160])
    return cleaned[:3]


def _looks_like_broken_structured_output(value: str) -> bool:
    if value.startswith("[") and not value.endswith("]"):
        return True
    if value.startswith("{") and not value.endswith("}"):
        return True
    return value.count('"') % 2 == 1


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
