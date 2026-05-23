from collections import Counter

from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.mod_search_service import build_summary_map
from app.services.agent.query_planner import DEFAULT_AGENT_LIMIT
from app.services.agent.reranker import validate_matches_with_llm
from app.services.agent.result_merger import (
    filter_by_adult_content,
    filter_by_distinctive_terms,
    merge_results,
    sort_results,
)
from app.services.agent.schemas import AgentModMatch
from app.services.agent.search_types import SearchPlan, SearchResult
from app.services.agent.semantic_search import distinctive_query_terms
from app.services.agent.tools.local_db_search_tool import (
    LocalDbSearchTool,
    local_db_input_from_plan,
)
from app.services.agent.tools.loverslab_google_search_tool import (
    LoversLabGoogleSearchTool,
    loverslab_google_input_from_plan,
)
from app.services.agent.tools.loverslab_search_scrape_tool import (
    LoversLabSearchScrapeTool,
    loverslab_scrape_input_from_plan,
)
from app.services.agent.tools.nexusmods_search_tool import (
    NexusModsSearchTool,
    nexus_tool_input_from_plan,
)


class AgentSearchOrchestrator:
    def __init__(self, session: Session):
        self.session = session

    async def find_matches(
        self,
        *,
        query: str,
        query_plan: dict,
        llm_available: bool,
        provider: str,
        api_key: str,
        base_url: str,
        model: str,
    ) -> list[AgentModMatch]:
        query_plan = _with_distinctive_keywords(query_plan, query)
        plan = SearchPlan.from_query_plan(query_plan)
        local_tool = LocalDbSearchTool(self.session)
        local_results = await local_tool.run(local_db_input_from_plan(query, plan.to_query_plan()))
        has_meaningful_local_matches = any(item.score > 1 for item in local_results)

        online_results: list[SearchResult] = []
        if not has_meaningful_local_matches or _should_query_online(plan.to_query_plan(), query):
            online_query_plan = _with_inferred_nexus_game(plan.to_query_plan(), query, local_results)
            online_results = await self._find_online_matches(query, online_query_plan)

        results = merge_results(online_results, local_results) if online_results else local_results
        results = filter_by_distinctive_terms(sort_results(results, plan), query)
        results = filter_by_adult_content(results, plan)
        matches = _matches_from_search_results(self.session, results, plan.limit) if results else []
        if llm_available and matches:
            matches = await validate_matches_with_llm(
                query=query,
                matches=matches,
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                query_plan=plan.to_query_plan(),
            )
        if matches:
            return matches

        retry_plan = dict(plan.to_query_plan())
        retry_plan["keywords"] = []
        retry_plan["sort_field"] = query_plan.get("sort_field") or "updated_at_remote"
        retry_plan["sort_order"] = query_plan.get("sort_order") or "desc"
        retry_plan["limit"] = int(query_plan.get("limit") or DEFAULT_AGENT_LIMIT)
        retry_search_plan = SearchPlan.from_query_plan(retry_plan)
        retry_results = await local_tool.run(local_db_input_from_plan(query, retry_search_plan.to_query_plan()))
        retry_results = filter_by_distinctive_terms(retry_results, query)
        retry_results = filter_by_adult_content(retry_results, retry_search_plan)
        if not retry_results:
            return []
        return _matches_from_search_results(self.session, retry_results, retry_search_plan.limit)

    async def _find_online_matches(self, query: str, query_plan: dict) -> list[SearchResult]:
        online_results: list[SearchResult] = []
        nexus_input = nexus_tool_input_from_plan(self.session, query, query_plan)
        if nexus_input is not None:
            online_results.extend(await NexusModsSearchTool(self.session).run(nexus_input))
        loverslab_input = loverslab_google_input_from_plan(query, query_plan)
        if loverslab_input is not None:
            loverslab_results = await LoversLabGoogleSearchTool(self.session).run(loverslab_input)
            online_results.extend(loverslab_results)
            if not loverslab_results:
                scrape_input = loverslab_scrape_input_from_plan(query, query_plan)
                if scrape_input is not None:
                    online_results.extend(await LoversLabSearchScrapeTool(self.session).run(scrape_input))
        return online_results


def _match_from_mod(mod: Mod, score: int, summary_by_mod: dict[int, str]) -> AgentModMatch:
    return AgentModMatch(
        id=mod.id or 0,
        title=mod.title,
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


def _matches_from_search_results(
    session: Session,
    results: list[SearchResult],
    limit: int,
) -> list[AgentModMatch]:
    top = results[:limit]
    mod_ids = [item.mod.id for item in top if item.mod.id is not None]
    summary_by_mod = build_summary_map(session, mod_ids)
    return [_match_from_mod(item.mod, item.score, summary_by_mod) for item in top]


def _has_explicit_online_source(query_plan: dict) -> bool:
    sources = {str(value).strip().lower() for value in (query_plan.get("sources") or []) if str(value).strip()}
    return bool(sources & {"nexusmods", "loverslab"})


def _should_query_online(query_plan: dict, query: str) -> bool:
    return _has_explicit_online_source(query_plan) or bool(distinctive_query_terms(query))


def _with_distinctive_keywords(query_plan: dict, query: str) -> dict:
    terms = distinctive_query_terms(query)
    if not terms:
        return query_plan
    keywords = [str(value).strip() for value in (query_plan.get("keywords") or []) if str(value).strip()]
    existing = {value.lower() for value in keywords}
    additions = [term for term in terms if term.lower() not in existing]
    if not additions:
        return query_plan
    updated = dict(query_plan)
    updated["keywords"] = [*keywords, *additions]
    return updated


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
