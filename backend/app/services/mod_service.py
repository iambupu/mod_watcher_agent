from typing import Literal

from sqlalchemy import or_
from sqlmodel import Session, func, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.settings_service import SettingsService
from app.services.summary_service import load_summary_map

SORT_WHITELIST = {"first_seen_at", "downloads", "endorsements", "updated_at_remote"}


class ModService:
    def __init__(self, session: Session):
        self.session = session

    def translation_enabled(self) -> bool:
        settings = SettingsService(self.session)
        provider = (settings.get("llm_provider") or "openai").strip().lower()
        api_key = settings.get("llm_api_key") or ""
        return provider == "ollama" or bool(api_key.strip())

    def get_summary_language(self) -> str:
        return SettingsService(self.session).get("summary_language") or "zh-CN"

    def _build_mod_conditions(
        self,
        game: str | None,
        source: str | None,
        search: str | None,
        adult_content: Literal["include", "exclude", "only"] | None,
    ):
        conditions = [Mod.ignored == False]
        if game is not None:
            conditions.append(or_(Mod.game == game, Mod.game_domain == game))
        if source is not None:
            conditions.append(Mod.source == source)
        if adult_content is not None:
            if adult_content == "exclude":
                conditions.append(Mod.adult_content == False)
            elif adult_content == "only":
                conditions.append(Mod.adult_content == True)
        if search is not None:
            conditions.append(Mod.title.ilike(f"%{search}%"))
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
    ) -> tuple[list[Mod], int, str, dict[int, str], dict[int, str], list[int]]:
        conditions = self._build_mod_conditions(game, source, search, adult_content)

        sort_map = {
            "first_seen_at": Mod.first_seen_at,
            "downloads": Mod.downloads,
            "endorsements": Mod.endorsements,
            "updated_at_remote": Mod.updated_at_remote,
        }
        if sort_by not in SORT_WHITELIST:
            sort_by = "first_seen_at"
        sort_column = sort_map[sort_by]

        base_stmt = select(Mod)
        if conditions:
            base_stmt = base_stmt.where(*conditions)

        count_stmt = select(func.count()).select_from(Mod)
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
    ) -> tuple[list[dict], int, str, list[int]]:
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
        stmt = (
            select(
                Mod.game_domain,
                Mod.game,
                func.count(Mod.id),
            )
            .where(Mod.ignored == False)
            .group_by(Mod.game_domain, Mod.game)
            .order_by(func.count(Mod.id).desc(), Mod.game.asc())
        )
        return self.session.exec(stmt).all()

    def get_mod_with_summaries(
        self,
        mod_id: int,
    ) -> tuple[Mod | None, str, str | None, str | None]:
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
        mod, language, translated_summary, ai_introduction = self.get_mod_with_summaries(mod_id)
        if mod is None:
            return None, language
        return self._to_display_dict(mod, translated_summary, ai_introduction), language

    def get_mod_or_none(self, mod_id: int) -> Mod | None:
        return self.session.get(Mod, mod_id)

    def delete_summary_if_exists(
        self,
        mod_id: int,
        language: str,
        summary_type: str,
    ) -> bool:
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
        row = self.session.exec(
            select(ModSummary).where(
                ModSummary.mod_id == mod_id,
                ModSummary.language == language,
                ModSummary.summary_type == summary_type,
            )
        ).first()
        return row.content if row else ""

    def mark_mod_ignored(self, mod_id: int) -> bool:
        mod = self.get_mod_or_none(mod_id)
        if mod is None:
            return False
        mod.ignored = True
        self.session.add(mod)
        self.session.commit()
        return True
