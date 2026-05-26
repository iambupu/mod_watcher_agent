import logging
from collections import Counter

from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.reranker import validate_matches_with_llm
from app.services.agent.schemas import AgentModMatch
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms
from app.services.agent.tools.candidate_recovery_tool import (
    CandidateRecoveryInput,
    CandidateRecoveryTool,
)
from app.services.agent.tools.llm_candidate_validator_tool import (
    LlmCandidateValidatorInput,
    LlmCandidateValidatorTool,
)
from app.services.agent.tools.local_db_search_tool import (
    LocalDbSearchTool,
    local_db_input_from_plan,
)
from app.services.agent.tools.match_materializer_tool import (
    MatchMaterializerInput,
    MatchMaterializerTool,
)
from app.services.agent.tools.result_fusion_ranker_tool import (
    ResultFusionRankerInput,
    ResultFusionRankerTool,
)
from app.services.agent.tools.vector_search_tool import VectorSearchInput, VectorSearchTool
from app.services.agent.tools.web_search_tool import WebSearchTool

logger = logging.getLogger(__name__)


class AgentSearchOrchestrator:
    def __init__(self, session: Session):
        self.session = session

    async def find_matches(
        self,
        *,
        query: str,
        query_plan: dict,
        evidence: list[dict[str, object]] | None = None,
        llm_available: bool,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
    ) -> list[AgentModMatch]:
        evidence_id = str(query_plan.get("evidence_id") or "").strip()
        query_plan = _with_distinctive_keywords(query_plan, query)
        plan = SearchPlan.from_query_plan(query_plan)
        plan_query = {**plan.to_query_plan(), "evidence_id": evidence_id}
        effective_query = _effective_search_query(query, plan)
        local_tool = LocalDbSearchTool(self.session)
        local_results = await local_tool.run(local_db_input_from_plan(effective_query, plan_query))
        _append_evidence(
            evidence,
            stage="local_retrieval",
            tool="local_db",
            status="succeeded",
            count=len(local_results),
            fields=_query_plan_fields(query_plan),
            evidence_id=evidence_id,
        )
        logger.info(
            "agent.search.local count=%s evidence_id=%s keywords=%s excluded_keywords=%s exclude_titles=%s excluded_sources=%s keyword_match_mode=%s exact_title=%s version=%s external_id=%s source_url=%s games=%s sources=%s categories=%s tags=%s summary_languages=%s excluded_summary_languages=%s requirement_terms=%s compatibility_terms=%s has_thumbnail=%s author=%s adult_content=%s min_downloads=%s min_endorsements=%s min_views=%s min_likes=%s updated_since_days=%s updated_after=%s updated_before=%s published_after=%s published_before=%s created_after=%s created_before=%s sort=%s/%s",
            len(local_results),
            evidence_id,
            plan.keywords,
            plan.excluded_keywords,
            _excluded_titles(query_plan),
            query_plan.get("excluded_sources", []),
            query_plan.get("keyword_match_mode"),
            plan.exact_title,
            plan.version,
            plan.external_id,
            plan.source_url,
            plan.games,
            plan.sources,
            plan.categories,
            plan.tags,
            plan.summary_languages,
            plan.excluded_summary_languages,
            plan.requirement_terms,
            plan.compatibility_terms,
            plan.has_thumbnail,
            plan.author,
            plan.adult_content,
            plan.min_downloads,
            plan.min_endorsements,
            plan.min_views,
            plan.min_likes,
            plan.updated_since_days,
            plan.updated_after,
            plan.updated_before,
            plan.published_after,
            plan.published_before,
            plan.created_after,
            plan.created_before,
            plan.sort_field,
            plan.sort_order,
        )
        vector_output = VectorSearchTool(enabled=False).run(
            VectorSearchInput(
                query=effective_query,
                filters=plan.to_query_plan(),
                limit=plan.limit,
                evidence_id=evidence_id,
            )
        )
        if evidence is not None:
            evidence.extend(vector_output.evidence)
        staged_results = [*local_results, *vector_output.results]
        has_meaningful_local_matches = any(item.score > 1 for item in staged_results)

        online_results: list[SearchResult] = []
        if not has_meaningful_local_matches or _should_query_online(plan_query, effective_query):
            online_query_plan = _with_inferred_nexus_game(plan_query, effective_query, local_results)
            web_output = await WebSearchTool(self.session).run(
                query=effective_query,
                query_plan=online_query_plan,
                evidence_id=evidence_id,
                conservative_mode=bool(query_plan.get("_agent_conservative_mode")),
            )
            online_results = web_output.results
            if evidence is not None:
                evidence.extend(web_output.evidence)
        else:
            logger.info(
                "agent.tool name=web_search status=skipped reason=local_matches_sufficient results=0 evidence_id=%s",
                evidence_id,
            )
            _append_evidence(
                evidence,
                stage="online_retrieval",
                tool="online_gate",
                status="skipped",
                count=0,
                reason="local_matches_sufficient",
                fields=["keywords", "sources", "games", "categories"],
                evidence_id=evidence_id,
            )
        logger.info("agent.search.online count=%s evidence_id=%s", len(online_results), evidence_id)

        fusion_output = ResultFusionRankerTool().run(
            ResultFusionRankerInput(
                query=query,
                query_plan=query_plan,
                plan=plan,
                staged_results=staged_results,
                online_results=online_results,
                evidence_id=evidence_id,
            )
        )
        results = fusion_output.results
        if evidence is not None:
            evidence.extend(fusion_output.evidence)
        matches = MatchMaterializerTool(self.session).run(
            MatchMaterializerInput(results=results, limit=plan.limit, evidence_id=evidence_id)
        ).matches
        validator_output = await LlmCandidateValidatorTool(validator=validate_matches_with_llm).run(
            LlmCandidateValidatorInput(
                query=query,
                matches=matches,
                llm_available=llm_available,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                query_plan=plan_query,
                evidence_id=evidence_id,
            )
        )
        matches = validator_output.matches
        if matches:
            return matches

        recovery_output = await CandidateRecoveryTool(self.session).run(
            CandidateRecoveryInput(
                query=query,
                search_query=effective_query,
                query_plan=query_plan,
                plan=plan,
                evidence_id=evidence_id,
            )
        )
        if evidence is not None:
            evidence.extend(recovery_output.evidence)
        return recovery_output.matches

def _append_evidence(
    evidence: list[dict[str, object]] | None,
    *,
    stage: str,
    tool: str,
    status: str,
    count: int,
    reason: str | None = None,
    fields: list[str] | None = None,
    evidence_id: str = "",
) -> None:
    if evidence is None:
        return
    fragment_id = f"r_{len(evidence) + 1}"
    item: dict[str, object] = {
        "fragment_id": fragment_id,
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


def _query_plan_fields(query_plan: dict) -> list[str]:
    field_keys = [
        "keywords",
        "games",
        "game_domains",
        "sources",
        "categories",
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
    active: list[str] = []
    for key in field_keys:
        value = query_plan.get(key)
        if value in (None, "", []):
            continue
        active.append(key)
    return active


def _has_explicit_online_source(query_plan: dict) -> bool:
    sources = {str(value).strip().lower() for value in (query_plan.get("sources") or []) if str(value).strip()}
    return bool(sources & {"nexusmods", "loverslab"})


def _should_query_online(query_plan: dict, query: str) -> bool:
    return _has_explicit_online_source(query_plan) or bool(distinctive_query_terms(query))


def _effective_search_query(query: str, plan: SearchPlan) -> str:
    visible_query = query.split("[scope]", 1)[0].strip()
    parts = [visible_query]
    if not distinctive_query_terms(visible_query):
        parts.extend([*plan.keywords, *plan.categories])
    seen: set[str] = set()
    values: list[str] = []
    for part in parts:
        value = str(part or "").strip()
        key = value.lower()
        if value and key not in seen:
            values.append(value)
            seen.add(key)
    return " ".join(values) or visible_query


def _excluded_titles(query_plan: dict) -> list[str]:
    raw = query_plan.get("exclude_titles")
    if not isinstance(raw, list):
        return []
    return [str(value).strip() for value in raw if str(value).strip()]


def _with_distinctive_keywords(query_plan: dict, query: str) -> dict:
    terms = distinctive_query_terms(query)
    if not terms:
        return query_plan
    author_key = _author_key(query_plan)
    excluded_keys = _slot_keys(query_plan.get("excluded_keywords"))
    game_keys = _slot_keys([*query_plan.get("games", []), *query_plan.get("game_domains", [])])
    tag_keys = _slot_keys(query_plan.get("tags"))
    summary_language_keys = (
        _slot_keys(query_plan.get("summary_languages"))
        | _slot_keys(query_plan.get("excluded_summary_languages"))
        | _summary_language_marker_keys()
    )
    requirement_keys = _slot_keys(query_plan.get("requirement_terms")) | _requirement_marker_keys()
    compatibility_keys = _slot_keys(query_plan.get("compatibility_terms")) | _compatibility_marker_keys()
    media_keys = _media_keys()
    exact_title_keys = _slot_keys([query_plan.get("exact_title")])
    version_keys = _slot_keys([query_plan.get("version"), f"v{query_plan.get('version')}" if query_plan.get("version") else ""])
    identity_keys = _slot_keys(
        [
            query_plan.get("external_id"),
            query_plan.get("source_url"),
            "id",
            "file",
            "resource",
            "nexusmods",
            "loverslab",
            "nexus",
            "nexuss",
            "ll",
            "llab",
            "lovers lab",
            "mod",
            "mods",
        ]
    )
    metric_keys = _metric_keys(query_plan)
    keywords = [str(value).strip() for value in (query_plan.get("keywords") or []) if str(value).strip()]
    existing = {value.lower() for value in keywords}
    additions = [
        term
        for term in terms
        if term.lower() not in existing
        and not _term_matches_author(term, author_key)
        and not _term_matches_slot(term, excluded_keys)
        and not _term_matches_slot(term, game_keys)
        and not _term_matches_slot(term, tag_keys)
        and not _term_matches_slot(term, summary_language_keys)
        and not _term_matches_slot(term, requirement_keys)
        and not _term_matches_slot(term, compatibility_keys)
        and not _term_matches_slot(term, media_keys)
        and not _term_matches_slot(term, exact_title_keys)
        and not _term_matches_slot(term, version_keys)
        and not _term_matches_slot(term, identity_keys)
        and not _term_matches_slot(term, metric_keys)
    ]
    if not additions:
        return query_plan
    updated = dict(query_plan)
    updated["keywords"] = [*keywords, *additions]
    return updated


def _author_key(query_plan: dict) -> str:
    return _compact_key(query_plan.get("author"))


def _term_matches_author(term: str, author_key: str) -> bool:
    key = _compact_key(term)
    return bool(key and author_key and (key in author_key or author_key in key))


def _slot_keys(values: object) -> set[str]:
    if isinstance(values, str):
        raw_values = [values]
    elif isinstance(values, list | tuple | set):
        raw_values = list(values)
    else:
        raw_values = []
    return {_compact_key(value) for value in raw_values if _compact_key(value)}


def _metric_keys(query_plan: dict) -> set[str]:
    raw_values = [
        query_plan.get("min_downloads"),
        query_plan.get("min_endorsements"),
        query_plan.get("min_views"),
        query_plan.get("min_likes"),
        query_plan.get("updated_since_days"),
        query_plan.get("updated_after"),
        query_plan.get("updated_before"),
        query_plan.get("published_after"),
        query_plan.get("published_before"),
        query_plan.get("created_after"),
        query_plan.get("created_before"),
        "download",
        "downloads",
        "endorsement",
        "endorsements",
        "view",
        "views",
        "like",
        "likes",
        "last",
        "past",
        "within",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
        "下载",
        "下载量",
        "背书",
        "点赞",
        "浏览",
        "浏览量",
        "喜欢",
        "喜欢数",
        "数",
        "最近",
        "过去",
        "天",
        "周",
        "月",
    ]
    return {_compact_key(value) for value in raw_values if _compact_key(value)}


def _media_keys() -> set[str]:
    raw_values = [
        "image",
        "images",
        "thumbnail",
        "preview",
        "preview image",
        "screenshot",
        "screenshots",
        "picture",
        "pictures",
        "图片",
        "图",
        "预览",
        "预览图",
        "截图",
        "封面图",
        "有图",
        "无图",
    ]
    return {_compact_key(value) for value in raw_values if _compact_key(value)}


def _summary_language_marker_keys() -> set[str]:
    raw_values = [
        "summary",
        "summaries",
        "description",
        "descriptions",
        "intro",
        "introduction",
        "chinese",
        "english",
        "japanese",
        "中文",
        "英文",
        "日文",
        "摘要",
        "介绍",
        "说明",
    ]
    return {_compact_key(value) for value in raw_values if _compact_key(value)}


def _requirement_marker_keys() -> set[str]:
    raw_values = [
        "require",
        "requires",
        "requiring",
        "required",
        "requirement",
        "requirements",
        "need",
        "needs",
        "needed",
        "dependency",
        "dependencies",
        "depends",
        "depends on",
        "dependent",
        "dependent on",
        "script",
        "extender",
        "script extender",
        "skyrim script extender",
        "前置",
        "依赖",
        "需要",
        "要求",
    ]
    return {_compact_key(value) for value in raw_values if _compact_key(value)}


def _compatibility_marker_keys() -> set[str]:
    raw_values = [
        "compatible",
        "compatibility",
        "support",
        "supports",
        "supported",
        "not compatible",
        "does not support",
        "for",
        "兼容",
        "支持",
        "适配",
        "不兼容",
        "不支持",
    ]
    return {_compact_key(value) for value in raw_values if _compact_key(value)}


def _term_matches_slot(term: str, slot_keys: set[str]) -> bool:
    key = _compact_key(term)
    return bool(key and any(key in slot_key or slot_key in key for slot_key in slot_keys))


def _compact_key(value: object) -> str:
    return "".join(str(value or "").lower().replace("_", "").replace("-", "").split())


def _with_inferred_nexus_game(query_plan: dict, query: str, results: list[SearchResult]) -> dict:
    if query_plan.get("games") or query_plan.get("game_domains"):
        return query_plan

    terms = distinctive_query_terms(query)
    candidates = [
        item.mod
        for item in results
        if item.mod.source == "nexusmods"
        and item.mod.game_domain
        and (not terms or _mod_contains_terms(item.mod, terms))
    ]
    if not candidates:
        return query_plan

    domain = Counter(str(mod.game_domain) for mod in candidates).most_common(1)[0][0]
    game = next((mod.game for mod in candidates if mod.game_domain == domain and mod.game), None)
    updated = dict(query_plan)
    updated["game_domains"] = [domain]
    if game:
        updated["games"] = [game]
    return updated


def _mod_contains_terms(mod: Mod, terms: list[str]) -> bool:
    haystack = " ".join(
        str(value or "")
        for value in [
            mod.title,
            mod.author,
            mod.category,
            mod.game,
            mod.game_domain,
            mod.original_summary,
        ]
    ).lower()
    return all(term in haystack for term in terms)
