from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentSkill:
    name: str
    description: str
    triggers: tuple[str, ...]
    required_slots: tuple[str, ...]
    optional_slots: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    can_run_in_parallel: bool
    output_contract: str = "AgentSkillResult"


@dataclass(frozen=True)
class AgentSkillResult:
    answer_payload: dict[str, Any]
    matches: list[Any]
    trace: dict[str, Any]
    confidence: float
    followup_questions: list[str]


_BUILTINS = {
    "mod_research": AgentSkill(
        name="mod_research",
        description="对用户指定的 Mod 需求进行多阶段检索、重排和研究式总结",
        triggers=("找", "推荐", "research", "类似", "最近更新"),
        required_slots=("query",),
        optional_slots=("game", "source", "adult_content", "sort"),
        allowed_tools=("structured_sql", "sqlite_fts", "qdrant_vector", "nexusmods_search", "loverslab_google"),
        can_run_in_parallel=False,
    ),
    "install_risk": AgentSkill(
        name="install_risk",
        description="总结安装风险、前置依赖、成人内容和版本注意事项",
        triggers=("风险", "安装", "前置", "兼容"),
        required_slots=("query",),
        optional_slots=("game", "source"),
        allowed_tools=("structured_sql", "sqlite_fts"),
        can_run_in_parallel=True,
    ),
    "alternative_research": AgentSkill(
        name="alternative_research",
        description="根据上下文需求寻找替代 Mod，并排除用户已看过或明确不想重复的候选",
        triggers=("替代", "平替", "换一个", "更稳", "alternative", "replacement", "safer"),
        required_slots=("query",),
        optional_slots=("game", "source", "adult_content", "exclude_titles"),
        allowed_tools=("structured_sql", "sqlite_fts", "qdrant_vector", "nexusmods_search", "loverslab_google"),
        can_run_in_parallel=False,
    ),
    "comparison_research": AgentSkill(
        name="comparison_research",
        description="比较多个候选 Mod，在新手友好、稳定性、风险和兼容性之间给出取舍建议",
        triggers=("哪个", "比较", "对比", "更适合", "风险更低", "which", "compare", "better"),
        required_slots=("query",),
        optional_slots=("candidate_titles", "game", "source", "adult_content"),
        allowed_tools=("structured_sql", "sqlite_fts", "qdrant_vector"),
        can_run_in_parallel=False,
    ),
    "preference_summary": AgentSkill(
        name="preference_summary",
        description="根据收藏和历史查询总结用户偏好",
        triggers=("偏好", "收藏", "喜欢"),
        required_slots=(),
        optional_slots=("game", "source"),
        allowed_tools=("structured_sql",),
        can_run_in_parallel=True,
    ),
}


def list_builtin_skills() -> set[str]:
    return set(_BUILTINS)


def get_builtin_skill(name: str) -> AgentSkill:
    return _BUILTINS[name]
