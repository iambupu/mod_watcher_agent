from typing import Literal

from sqlalchemy import or_
from sqlmodel import Session, func, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.agent.semantic_search import semantic_query, unique_terms
from app.services.llm_provider_config import get_provider_chain, provider_config_has_credentials
from app.services.settings_service import SettingsService
from app.services.summary_service import load_summary_map

SORT_WHITELIST = {"first_seen_at", "downloads", "endorsements", "updated_at_remote"}


class ModService:
    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    def translation_enabled(self) -> bool:
        """处理当前模块的业务逻辑并返回结果。"""
        settings = SettingsService(self.session)
        return any(provider_config_has_credentials(provider) for provider in get_provider_chain(settings))

    def get_summary_language(self) -> str:
        """读取并返回对应的数据。"""
        return SettingsService(self.session).get("summary_language") or "zh-CN"

    def _build_mod_conditions(
        self,
        game: str | None,
        source: str | None,
        search: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        *,
        ignored: bool = False,
    ):
        """构建内部流程需要的数据结构。"""
        conditions = [Mod.ignored == ignored]
        if game is not None:
            conditions.append(or_(Mod.game == game, Mod.game_domain == game))
        if source is not None:
            conditions.append(Mod.source == source)
        if adult_content is not None:
            if adult_content == "exclude":
                conditions.append(Mod.adult_content == False)  # noqa: E712
            elif adult_content == "only":
                conditions.append(Mod.adult_content == True)  # noqa: E712
        if search is not None and search.strip():
            terms = _search_terms(search)
            conditions.append(
                or_(
                    *[
                        or_(
                            Mod.title.ilike(f"%{term}%"),
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
            )
        return conditions

    def list_mods_with_summaries(
        self,
        game: str | None,
        source: str | None,
        search: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        sort_by: str,
        sort_order: str,
        offset: int,
        limit: int,
        *,
        ignored: bool = False,
    ) -> tuple[list[Mod], int, str, dict[int, str], dict[int, str], list[int]]:
        """查询并返回列表数据。"""
        conditions = self._build_mod_conditions(game, source, search, adult_content, ignored=ignored)

        sort_map = {
            "first_seen_at": Mod.first_seen_at,
            "downloads": Mod.downloads,
            "endorsements": Mod.endorsements,
            "updated_at_remote": Mod.updated_at_remote,
        }
        if sort_by not in SORT_WHITELIST:
            sort_by = "first_seen_at"
        sort_column = sort_map[sort_by]

        base_stmt = select(Mod).outerjoin(ModSummariesForSearch, ModSummariesForSearch.mod_id == Mod.id)
        if conditions:
            base_stmt = base_stmt.where(*conditions)
        base_stmt = base_stmt.distinct()

        count_stmt = select(func.count(func.distinct(Mod.id))).select_from(Mod).outerjoin(
            ModSummariesForSearch,
            ModSummariesForSearch.mod_id == Mod.id,
        )
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
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        data = mod.model_dump()
        data["translated_summary"] = translated_summary
        data["ai_introduction"] = ai_introduction
        return data

    def list_mod_displays(
        self,
        game: str | None,
        source: str | None,
        search: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
        sort_by: str,
        sort_order: str,
        offset: int,
        limit: int,
        *,
        ignored: bool = False,
    ) -> tuple[list[dict], int, str, list[int]]:
        """查询并返回列表数据。"""
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

    def list_game_options(self) -> list[tuple[str, str, int]]:
        """查询并返回列表数据。"""
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
        """读取并返回对应的数据。"""
        mod = self.session.get(Mod, mod_id)
        language = self.get_summary_language()
        if mod is None:
            return None, language, None, None

        summary_rows = self.session.exec(
            select(ModSummary).where(
                ModSummary.mod_id == mod_id,
                ModSummary.language == language,
                ModSummary.summary_type.in_(["brief", "introduction"]),
            )
        ).all()
        translated_summary = None
        ai_introduction = None
        for row in summary_rows:
            if row.summary_type == "brief":
                translated_summary = row.content
            elif row.summary_type == "introduction":
                ai_introduction = row.content
        return mod, language, translated_summary, ai_introduction

    def get_mod_display(self, mod_id: int) -> tuple[dict | None, str]:
        """读取并返回对应的数据。"""
        mod, language, translated_summary, ai_introduction = self.get_mod_with_summaries(mod_id)
        if mod is None:
            return None, language
        return self._to_display_dict(mod, translated_summary, ai_introduction), language

    def get_mod_or_none(self, mod_id: int) -> Mod | None:
        """读取并返回对应的数据。"""
        return self.session.get(Mod, mod_id)

    def delete_summary_if_exists(
        self,
        mod_id: int,
        language: str,
        summary_type: str,
    ) -> bool:
        """删除对应数据并返回处理结果。"""
        existing = self.session.exec(
            select(ModSummary).where(
                ModSummary.mod_id == mod_id,
                ModSummary.language == language,
                ModSummary.summary_type == summary_type,
            )
        ).first()
        if not existing:
            return False
        self.session.delete(existing)
        self.session.commit()
        return True

    def get_summary_content(
        self,
        mod_id: int,
        language: str,
        summary_type: str,
    ) -> str:
        """读取并返回对应的数据。"""
        row = self.session.exec(
            select(ModSummary).where(
                ModSummary.mod_id == mod_id,
                ModSummary.language == language,
                ModSummary.summary_type == summary_type,
            )
        ).first()
        return row.content if row else ""

    def mark_mod_ignored(self, mod_id: int) -> bool:
        """标记状态变更并返回结果。"""
        mod = self.get_mod_or_none(mod_id)
        if mod is None:
            return False
        mod.ignored = True
        self.session.add(mod)
        self.session.commit()
        return True

    def mark_mod_visible(self, mod_id: int) -> bool:
        """标记状态变更并返回结果。"""
        mod = self.get_mod_or_none(mod_id)
        if mod is None:
            return False
        mod.ignored = False
        self.session.add(mod)
        self.session.commit()
        return True


ModSummariesForSearch = ModSummary


def _search_terms(search: str) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    semantic = semantic_query(search)
    return unique_terms([semantic.clean_query, *semantic.all_terms])[:12]
