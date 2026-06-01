from dataclasses import dataclass

from sqlmodel import Session

from app.services.agent.mod_search_service import query_mods_with_plan
from app.services.agent.search_types import SearchPlan, SearchResult


@dataclass(frozen=True)
class LocalDbSearchInput:
    query: str
    plan: SearchPlan
    evidence_id: str = ""


class LocalDbSearchTool:
    """检索本地已存储 MOD，承担离线优先路径和硬过滤落点。"""

    name = "local_db_search"

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    async def run(self, tool_input: LocalDbSearchInput) -> list[SearchResult]:
        """执行任务流程并返回结果。"""
        plan = tool_input.plan.to_query_plan()
        if tool_input.evidence_id:
            plan["evidence_id"] = tool_input.evidence_id
        scored = query_mods_with_plan(self.session, tool_input.query, plan)
        return [SearchResult(score=score, mod=mod, tool_name=self.name) for score, mod in scored]


def local_db_input_from_plan(query: str, plan: dict) -> LocalDbSearchInput:
    """处理当前模块的业务逻辑并返回结果。"""
    return LocalDbSearchInput(
        query=query,
        plan=SearchPlan.from_query_plan(plan),
        evidence_id=str(plan.get("evidence_id") or "").strip(),
    )
