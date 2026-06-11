from typing import Literal

from sqlalchemy import or_, text
from sqlmodel import Session, func, select

from app.models.favorite import Favorite
from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.memory.favorite_preference_summarizer import summarize_favorite_preferences
from app.services.agent.memory.preference_service import AgentPreferenceService
from app.services.agent.retrievers.sqlite_fts_retriever import ensure_mods_fts, rebuild_mods_fts
from app.services.agent.semantic_search import semantic_query, unique_terms
from app.services.llm_provider_config import get_provider_chain, provider_config_has_credentials
from app.services.settings_service import SettingsService
from app.services.summary_service import load_summary_map

MOD_SORT_COLUMNS = {
    "first_seen_at": Mod.first_seen_at,
    "downloads": Mod.downloads,
    "endorsements": Mod.endorsements,
    "updated_at_remote": Mod.updated_at_remote,
}
MOD_SORT_SQL_COLUMNS = {
    "first_seen_at": "m.first_seen_at",
    "downloads": "COALESCE(m.downloads, 0)",
    "endorsements": "COALESCE(m.endorsements, 0)",
    "updated_at_remote": "COALESCE(m.updated_at_remote, '')",
}
SORT_WHITELIST = set(MOD_SORT_COLUMNS)
RECOMMENDATION_PREFETCH_LIMIT = 250
CONTENT_LANGUAGE_KEYWORDS: dict[str, list[str]] = {
    "en": ["english", "en", "英文", "英语", "英語"],
    "zh": ["chinese", "zh", "中文", "汉化", "漢化", "简体", "繁體", "简中", "繁中"],
    "ja": ["japanese", "ja", "日文", "日语", "日本語"],
    "ko": ["korean", "ko", "韩文", "韩语", "韓文", "韓語", "한글", "한국어"],
    "ru": ["russian", "ru", "俄文", "俄语", "рус"],
}


class ModService:
    def __init__(self, session: Session):
        """保存数据库会话，用于查询 Mod、摘要和推荐偏好。"""
        self.session = session

    def translation_enabled(self) -> bool:
        """判断当前是否存在可用 LLM provider 用于生成摘要。"""
        settings = SettingsService(self.session)
        return any(provider_config_has_credentials(provider) for provider in get_provider_chain(settings))

    def get_summary_language(self) -> str:
        """读取摘要目标语言，未配置时默认简体中文。"""
        return SettingsService(self.session).get("summary_language") or "zh-CN"

    def _build_mod_conditions(
        self,
        game: str | None,
        source: str | None,
        content_language: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        *,
        ignored: bool = False,
    ):
        """构建 Mod 列表查询的通用过滤条件。"""
        conditions = [Mod.ignored == ignored]
        if game is not None:
            conditions.append(or_(Mod.game == game, Mod.game_domain == game))
        if source is not None:
            conditions.append(Mod.source == source)
        language_condition = self._build_content_language_condition(content_language)
        if language_condition is not None:
            conditions.append(language_condition)
        if adult_content is not None:
            if adult_content == "exclude":
                conditions.append(Mod.adult_content == False)  # noqa: E712
            elif adult_content == "only":
                conditions.append(Mod.adult_content == True)  # noqa: E712
        return conditions

    def _build_content_language_condition(self, content_language: str | None):
        language_key = (content_language or "").strip().lower()
        if not language_key or language_key == "any":
            return None
        keywords = CONTENT_LANGUAGE_KEYWORDS.get(language_key)
        if not keywords:
            return None
        clauses = []
        for keyword in keywords:
            pattern = f"%{keyword}%"
            clauses.append(Mod.tags_json.ilike(pattern))
            clauses.append(Mod.title.ilike(pattern))
            clauses.append(Mod.original_summary.ilike(pattern))
        return or_(*clauses)

    def list_mods_with_summaries(
        self,
        game: str | None,
        source: str | None,
        search: str | None,
        content_language: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        sort_by: str,
        sort_order: str,
        offset: int,
        limit: int,
        *,
        ignored: bool = False,
    ) -> tuple[list[Mod], int, str, dict[int, str], dict[int, str], list[int]]:
        """分页查询 Mod，并返回对应语言的简短摘要和介绍映射。"""
        conditions = self._build_mod_conditions(game, source, content_language, adult_content, ignored=ignored)
        has_search = bool(search and search.strip())

        sort_by = _normalize_sort_by(sort_by)
        sort_column = _mod_sort_column(sort_by)

        items: list[Mod]
        terms = _search_terms(search or "") if has_search else []
        if has_search and not terms:
            return [], 0, self.get_summary_language(), {}, {}, []
        if has_search and self.session.get_bind().dialect.name == "sqlite":
            items, total = self._list_mods_with_sqlite_fts(
                terms=terms,
                game=game,
                source=source,
                content_language=content_language,
                adult_content=adult_content,
                sort_by=sort_by,
                sort_order=sort_order,
                offset=offset,
                limit=limit,
                ignored=ignored,
            )
        else:
            base_stmt = select(Mod)
            if has_search:
                search_condition = _build_mod_search_condition(terms)
                base_stmt = base_stmt.outerjoin(
                    ModSummariesForSearch,
                    ModSummariesForSearch.mod_id == Mod.id,
                ).where(search_condition)

            if conditions:
                base_stmt = base_stmt.where(*conditions)

            count_stmt = select(func.count(Mod.id)).select_from(Mod)
            if has_search:
                search_condition = _build_mod_search_condition(terms)
                base_stmt = base_stmt.distinct()
                count_stmt = select(func.count(func.distinct(Mod.id))).select_from(Mod).outerjoin(
                    ModSummariesForSearch,
                    ModSummariesForSearch.mod_id == Mod.id,
                ).where(search_condition)
            if conditions:
                count_stmt = count_stmt.where(*conditions)
            total = self.session.exec(count_stmt).one()

            if sort_order == "desc":
                base_stmt = base_stmt.order_by(sort_column.desc())
            else:
                base_stmt = base_stmt.order_by(sort_column.asc())

            items = self.session.exec(base_stmt.offset(offset).limit(limit)).all()
        language = self.get_summary_language()
        mod_ids = [item.id for item in items if item.id is not None]
        summary_by_mod = load_summary_map(self.session, mod_ids, language, "brief")
        introduction_by_mod = load_summary_map(self.session, mod_ids, language, "introduction")
        missing_ids = [
            item.id
            for item in items
            if item.id is not None
            and item.id not in summary_by_mod
            and (item.original_summary or item.title)
        ]
        return items, total, language, summary_by_mod, introduction_by_mod, missing_ids

    @staticmethod
    def _to_display_dict(
        mod: Mod,
        translated_summary: str | None = None,
        ai_introduction: str | None = None,
    ) -> dict:
        """把 Mod 模型转换为前端展示字典并补入 AI 摘要。"""
        data = mod.model_dump()
        data["translated_summary"] = translated_summary
        data["ai_introduction"] = ai_introduction
        return data

    def list_mod_displays(
        self,
        game: str | None,
        source: str | None,
        search: str | None,
        content_language: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        sort_by: str,
        sort_order: str,
        offset: int,
        limit: int,
        *,
        ignored: bool = False,
    ) -> tuple[list[dict], int, str, list[int]]:
        """返回前端列表可直接消费的 Mod 展示数据。"""
        (
            items,
            total,
            language,
            summary_by_mod,
            introduction_by_mod,
            missing_ids,
        ) = self.list_mods_with_summaries(
            game=game,
            source=source,
            search=search,
            content_language=content_language,
            adult_content=adult_content,
            sort_by=sort_by,
            sort_order=sort_order,
            offset=offset,
            limit=limit,
            ignored=ignored,
        )
        displays = [
            self._to_display_dict(
                item,
                translated_summary=summary_by_mod.get(item.id) if item.id is not None else None,
                ai_introduction=introduction_by_mod.get(item.id) if item.id is not None else None,
            )
            for item in items
        ]
        return displays, total, language, missing_ids

    def _list_mods_with_sqlite_fts(
        self,
        *,
        terms: list[str],
        game: str | None,
        source: str | None,
        content_language: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        sort_by: str,
        sort_order: str,
        offset: int,
        limit: int,
        ignored: bool,
    ) -> tuple[list[Mod], int]:
        if not terms:
            return [], 0

        if not self._ensure_sqlite_fts_ready():
            return self._list_mods_with_like_fallback(
                terms=terms,
                game=game,
                source=source,
                content_language=content_language,
                adult_content=adult_content,
                sort_by=sort_by,
                sort_order=sort_order,
                offset=offset,
                limit=limit,
                ignored=ignored,
            )

        where_clauses = ["m.ignored = :ignored"]
        params: dict[str, object] = {"ignored": 1 if ignored else 0}
        if game is not None:
            where_clauses.append("(m.game = :game OR m.game_domain = :game)")
            params["game"] = game
        if source is not None:
            where_clauses.append("m.source = :source")
            params["source"] = source
        language_key = (content_language or "").strip().lower()
        keywords = CONTENT_LANGUAGE_KEYWORDS.get(language_key)
        if keywords:
            language_terms: list[str] = []
            for idx, keyword in enumerate(keywords):
                key = f"content_language_{idx}"
                params[key] = f"%{keyword}%"
                language_terms.append(
                    f"(m.tags_json LIKE :{key} OR m.title LIKE :{key} OR m.original_summary LIKE :{key})"
                )
            where_clauses.append("(" + " OR ".join(language_terms) + ")")
        if adult_content is not None:
            if adult_content == "exclude":
                where_clauses.append("m.adult_content = 0")
            elif adult_content == "only":
                where_clauses.append("m.adult_content = 1")

        search_fragments: list[str] = []
        match_query = _fts_or_query(terms)
        if match_query:
            search_fragments.append(
                "m.id IN (SELECT mod_id FROM mods_fts WHERE mods_fts MATCH :match_query)"
            )
            params["match_query"] = match_query

        probe_terms = [term for term in terms if _requires_like_probe(term)]
        per_term_direct: list[str] = []
        for idx, term in enumerate(probe_terms):
            key = f"term_like_{idx}"
            params[key] = f"%{term}%"
            probe_columns = _probe_like_columns(term)
            term_conditions = " OR ".join(f"{column} LIKE :{key}" for column in probe_columns)
            per_term_direct.append(
                f"({term_conditions})"
            )
        if per_term_direct:
            search_fragments.append(
                "m.id IN (SELECT mod_id FROM mods_fts WHERE " + " OR ".join(per_term_direct) + ")"
            )

        if search_fragments:
            where_clauses.append("(" + " OR ".join(search_fragments) + ")")
        else:
            return [], 0
        where_sql = " AND ".join(where_clauses)

        direction = _mod_sort_sql_direction(sort_order)
        order_sql = f"{_mod_sort_sql_column(sort_by)} {direction}, m.id {direction}"

        count_sql = text(f"SELECT COUNT(1) AS total FROM mods m WHERE {where_sql}")
        total = int(self.session.execute(count_sql, params).scalar_one() or 0)
        if total <= 0:
            return [], 0

        page_sql = text(
            f"""
            SELECT m.id
            FROM mods m
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT :limit OFFSET :offset
            """
        )
        page_ids = [
            int(row[0])
            for row in self.session.execute(
                page_sql,
                {**params, "limit": int(limit), "offset": int(offset)},
            ).all()
        ]
        if not page_ids:
            return [], total

        rows = self.session.exec(select(Mod).where(Mod.id.in_(page_ids))).all()
        row_by_id = {int(row.id): row for row in rows if row.id is not None}
        ordered_items = [row_by_id[row_id] for row_id in page_ids if row_id in row_by_id]
        return ordered_items, total

    def _ensure_sqlite_fts_ready(self) -> bool:
        if self.session.get_bind().dialect.name != "sqlite":
            return False
        try:
            ensure_mods_fts(self.session)
        except Exception:
            self.session.rollback()
            return False
        try:
            fts_count = int(self.session.execute(text("SELECT COUNT(1) FROM mods_fts")).scalar_one() or 0)
            mod_count = int(
                self.session.execute(text("SELECT COUNT(1) FROM mods WHERE id IS NOT NULL")).scalar_one()
                or 0
            )
        except Exception:
            self.session.rollback()
            return False
        if mod_count > 0 and fts_count <= 0:
            rebuild_mods_fts(self.session)
        return True

    def _list_mods_with_like_fallback(
        self,
        *,
        terms: list[str],
        game: str | None,
        source: str | None,
        content_language: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        sort_by: str,
        sort_order: str,
        offset: int,
        limit: int,
        ignored: bool,
    ) -> tuple[list[Mod], int]:
        conditions = self._build_mod_conditions(game, source, content_language, adult_content, ignored=ignored)
        if not terms:
            return [], 0
        search_condition = _build_mod_search_condition(terms)

        sort_column = _mod_sort_column(sort_by)

        base_stmt = (
            select(Mod)
            .outerjoin(ModSummariesForSearch, ModSummariesForSearch.mod_id == Mod.id)
            .where(*conditions, search_condition)
            .distinct()
        )
        count_stmt = (
            select(func.count(func.distinct(Mod.id)))
            .select_from(Mod)
            .outerjoin(ModSummariesForSearch, ModSummariesForSearch.mod_id == Mod.id)
            .where(*conditions, search_condition)
        )
        total = self.session.exec(count_stmt).one()
        if sort_order == "desc":
            base_stmt = base_stmt.order_by(sort_column.desc())
        else:
            base_stmt = base_stmt.order_by(sort_column.asc())
        items = self.session.exec(base_stmt.offset(offset).limit(limit)).all()
        return items, total

    def list_recommended_mod_displays(self, limit: int = 5) -> tuple[list[dict], int, str, list[int]]:
        """Return mods associated with the stored user preference profile."""
        preferences = self._load_or_refresh_preferences()
        favorite_summary = preferences.get("favorite_summary") if isinstance(preferences, dict) else {}
        context = preferences.get("last_query_context") if isinstance(preferences, dict) else {}
        profile = _recommendation_profile(favorite_summary, context)

        favorite_mod_ids = set(self.session.exec(select(Favorite.mod_id)).all())
        candidates = self._recommendation_candidates(profile, favorite_mod_ids)
        if not candidates:
            candidates = self._fallback_recommendation_candidates(favorite_mod_ids)

        scored = [
            (_recommendation_score(mod, profile), mod)
            for mod in candidates
            if mod.id is not None
        ]
        scored.sort(key=lambda item: (item[0], item[1].downloads or 0, item[1].endorsements or 0, item[1].first_seen_at), reverse=True)
        selected = [mod for _score, mod in scored[:limit]]
        language = self.get_summary_language()
        mod_ids = [mod.id for mod in selected if mod.id is not None]
        summary_by_mod = load_summary_map(self.session, mod_ids, language, "brief")
        introduction_by_mod = load_summary_map(self.session, mod_ids, language, "introduction")
        missing_ids = [
            mod.id
            for mod in selected
            if mod.id is not None
            and mod.id not in summary_by_mod
            and (mod.original_summary or mod.title)
        ]
        displays = [
            self._to_display_dict(
                mod,
                translated_summary=summary_by_mod.get(mod.id) if mod.id is not None else None,
                ai_introduction=introduction_by_mod.get(mod.id) if mod.id is not None else None,
            )
            for mod in selected
        ]
        return displays, len(scored), language, missing_ids

    def _load_or_refresh_preferences(self) -> dict:
        preference_service = AgentPreferenceService(self.session)
        preferences = preference_service.load_preferences()
        favorite_summary = preferences.get("favorite_summary")
        if preference_service.is_dirty() or not isinstance(favorite_summary, dict) or not favorite_summary:
            favorite_summary = summarize_favorite_preferences(self.session)
            preferences = preference_service.save_preferences({"favorite_summary": favorite_summary})
        return preferences

    def _recommendation_candidates(self, profile: dict, favorite_mod_ids: set[int]) -> list[Mod]:
        conditions = [Mod.ignored == False]  # noqa: E712
        if favorite_mod_ids:
            conditions.append(Mod.id.not_in(favorite_mod_ids))
        if profile.get("adult_content_allowed") is False:
            conditions.append(or_(Mod.adult_content == False, Mod.adult_content.is_(None)))  # noqa: E712

        association_conditions = []
        if profile["games"]:
            association_conditions.append(Mod.game.in_(profile["games"]))
        if profile["sources"]:
            association_conditions.append(Mod.source.in_(profile["sources"]))
        if profile["categories"]:
            association_conditions.append(Mod.category.in_(profile["categories"]))
        if not association_conditions:
            return []

        stmt = (
            select(Mod)
            .where(*conditions, or_(*association_conditions))
            .order_by(Mod.downloads.desc(), Mod.endorsements.desc(), Mod.first_seen_at.desc())
            .limit(RECOMMENDATION_PREFETCH_LIMIT)
        )
        return self.session.exec(stmt).all()

    def _fallback_recommendation_candidates(self, favorite_mod_ids: set[int]) -> list[Mod]:
        conditions = [Mod.ignored == False]  # noqa: E712
        if favorite_mod_ids:
            conditions.append(Mod.id.not_in(favorite_mod_ids))
        stmt = (
            select(Mod)
            .where(*conditions)
            .order_by(Mod.downloads.desc(), Mod.endorsements.desc(), Mod.first_seen_at.desc())
            .limit(RECOMMENDATION_PREFETCH_LIMIT)
        )
        return self.session.exec(stmt).all()

    def list_game_options(self) -> list[tuple[str, str, int]]:
        """统计未忽略 Mod 中可供筛选的游戏选项。"""
        stmt = (
            select(
                Mod.game_domain,
                Mod.game,
                func.count(Mod.id),
            )
            .where(Mod.ignored == False)  # noqa: E712
            .group_by(Mod.game_domain, Mod.game)
            .order_by(func.count(Mod.id).desc(), Mod.game.asc())
        )
        return self.session.exec(stmt).all()

    def get_mod_with_summaries(
        self,
        mod_id: int,
    ) -> tuple[Mod | None, str, str | None, str | None]:
        """读取单个 Mod 及其首选语言下的简短摘要和介绍。"""
        mod = self.session.get(Mod, mod_id)
        language = self.get_summary_language()
        if mod is None:
            return None, language, None, None

        summary_by_mod = load_summary_map(self.session, [mod_id], language, "brief")
        introduction_by_mod = load_summary_map(self.session, [mod_id], language, "introduction")
        translated_summary = summary_by_mod.get(mod_id)
        ai_introduction = introduction_by_mod.get(mod_id)
        return mod, language, translated_summary, ai_introduction

    def get_mod_display(self, mod_id: int) -> tuple[dict | None, str]:
        """读取单个 Mod 的前端展示字典。"""
        mod, language, translated_summary, ai_introduction = self.get_mod_with_summaries(mod_id)
        if mod is None:
            return None, language
        return self._to_display_dict(mod, translated_summary, ai_introduction), language

    def get_mod_or_none(self, mod_id: int) -> Mod | None:
        """按 ID 读取 Mod，未找到时返回 None。"""
        return self.session.get(Mod, mod_id)

    def get_summary_content(
        self,
        mod_id: int,
        language: str,
        summary_type: str,
    ) -> str:
        """读取指定语言和类型的摘要正文。"""
        row = self.session.exec(
            select(ModSummary).where(
                ModSummary.mod_id == mod_id,
                ModSummary.language == language,
                ModSummary.summary_type == summary_type,
            )
        ).first()
        return row.content if row else ""

    def mark_mod_ignored(self, mod_id: int) -> bool:
        """把 Mod 标记为忽略并返回是否成功。"""
        mod = self.get_mod_or_none(mod_id)
        if mod is None:
            return False
        mod.ignored = True
        self.session.add(mod)
        self.session.commit()
        return True

    def mark_mod_visible(self, mod_id: int) -> bool:
        """取消 Mod 忽略状态并返回是否成功。"""
        mod = self.get_mod_or_none(mod_id)
        if mod is None:
            return False
        mod.ignored = False
        self.session.add(mod)
        self.session.commit()
        return True


ModSummariesForSearch = ModSummary


def _normalize_sort_by(sort_by: str) -> str:
    return sort_by if sort_by in SORT_WHITELIST else "first_seen_at"


def _mod_sort_column(sort_by: str):
    return MOD_SORT_COLUMNS[_normalize_sort_by(sort_by)]


def _mod_sort_sql_column(sort_by: str) -> str:
    return MOD_SORT_SQL_COLUMNS[_normalize_sort_by(sort_by)]


def _mod_sort_sql_direction(sort_order: str) -> str:
    return "DESC" if sort_order == "desc" else "ASC"


def _build_mod_search_condition(terms: list[str]):
    """Build the shared LIKE search condition for mod list queries."""
    return or_(
        *[
            or_(
                Mod.title.ilike(f"%{term}%"),
                Mod.translated_title_zh.ilike(f"%{term}%"),
                Mod.external_id.ilike(f"%{term}%"),
                Mod.author.ilike(f"%{term}%"),
                Mod.category.ilike(f"%{term}%"),
                Mod.game.ilike(f"%{term}%"),
                Mod.game_domain.ilike(f"%{term}%"),
                Mod.url.ilike(f"%{term}%"),
                Mod.tags_json.ilike(f"%{term}%"),
                Mod.original_summary.ilike(f"%{term}%"),
                ModSummariesForSearch.content.ilike(f"%{term}%"),
            )
            for term in terms
        ]
    )


def _search_terms(search: str) -> list[str]:
    """把用户搜索词扩展为语义检索和 FTS 共用的去重词组。"""
    semantic = semantic_query(search)
    return unique_terms([semantic.clean_query, *semantic.all_terms])[:12]


def _fts_or_query(terms: list[str]) -> str:
    cleaned: list[str] = []
    for term in terms:
        value = str(term or "").strip()
        if not value:
            continue
        if _is_ascii_alnum_token(value):
            cleaned.append(f"{value.lower()}*")
            continue
        escaped = value.replace('"', '""')
        cleaned.append(f'"{escaped}"')
    if not cleaned:
        return ""
    return " OR ".join(cleaned)


def _requires_like_probe(term: str) -> bool:
    value = str(term or "").strip()
    if not value:
        return False
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _is_ascii_alnum_token(value: str) -> bool:
    if " " in value or len(value) < 3:
        return False
    return all(("a" <= ch.lower() <= "z") or ch.isdigit() for ch in value)


def _probe_like_columns(term: str) -> tuple[str, ...]:
    if any("\u4e00" <= char <= "\u9fff" for char in term):
        return (
            "title",
            "translated_title_zh",
            "category",
            "original_summary",
            "translated_summary",
        )
    return (
        "title",
        "translated_title_zh",
        "external_id",
        "author",
        "category",
        "game",
        "game_domain",
        "url",
        "tags_json",
        "original_summary",
        "translated_summary",
    )


def _profile_values(raw: object) -> list[str]:
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        return []
    values: list[str] = []
    seen: set[str] = set()
    for item in raw:
        value = str(item or "").strip()
        key = value.lower()
        if value and key not in seen:
            values.append(value)
            seen.add(key)
    return values[:5]


def _recommendation_profile(favorite_summary: object, context: object) -> dict:
    favorite_summary = favorite_summary if isinstance(favorite_summary, dict) else {}
    context = context if isinstance(context, dict) else {}
    games = _merge_profile_values(
        _profile_values(favorite_summary.get("top_games")),
        _profile_values(context.get("top_games") or context.get("game") or context.get("games")),
    )
    sources = _merge_profile_values(
        _profile_values(favorite_summary.get("top_sources")),
        _profile_values(context.get("top_sources") or context.get("source") or context.get("sources")),
    )
    categories = _merge_profile_values(
        _profile_values(favorite_summary.get("top_categories")),
        _profile_values(context.get("top_categories") or context.get("category") or context.get("categories")),
    )
    adult_allowed = favorite_summary.get("adult_content_allowed")
    if adult_allowed is None:
        adult_allowed = context.get("adult_content_preference")
    return {
        "games": games,
        "sources": [source.lower() for source in sources],
        "categories": categories,
        "adult_content_allowed": adult_allowed,
    }


def _merge_profile_values(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for value in group:
            key = value.lower()
            if key not in seen:
                merged.append(value)
                seen.add(key)
    return merged[:5]


def _ranked_match(value: str | None, preferred: list[str], weight: int) -> int:
    if not value:
        return 0
    normalized = value.strip().lower()
    for index, item in enumerate(preferred):
        if normalized == item.strip().lower():
            return max(weight - index, 1)
    return 0


def _recommendation_score(mod: Mod, profile: dict) -> int:
    score = 0
    score += _ranked_match(mod.game, profile["games"], 60)
    score += _ranked_match(mod.source, profile["sources"], 30)
    score += _ranked_match(mod.category, profile["categories"], 45)
    if profile.get("adult_content_allowed") is True and mod.adult_content is True:
        score += 8
    if mod.updated_at_remote:
        score += 3
    if mod.thumbnail_url:
        score += 2
    return score
