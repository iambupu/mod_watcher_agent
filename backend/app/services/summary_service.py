import asyncio
import json
import logging
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.llm_client import create_llm_client
from app.services.llm_provider_config import (
    get_provider_chain,
    provider_config_has_credentials,
    resolve_provider_config,
)
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)
SUMMARY_GENERATION_LOCK = asyncio.Lock()
SUMMARY_LLM_TIMEOUT_SECONDS = 90.0


def load_summary_map(
    session: Session,
    mod_ids: list[int],
    language: str,
    summary_type: str,
    *,
    fallback_language: str | None = None,
) -> dict[int, str]:
    """加载配置或持久化数据。"""
    if not mod_ids:
        return {}
    languages = [language]
    if fallback_language and fallback_language != language:
        languages.append(fallback_language)
    rows = session.exec(
        select(ModSummary)
        .where(
            ModSummary.mod_id.in_(mod_ids),
            ModSummary.language.in_(languages),
            ModSummary.summary_type == summary_type,
        )
        .order_by(ModSummary.id.desc())
    ).all()
    primary_by_mod: dict[int, str] = {}
    fallback_by_mod: dict[int, str] = {}
    for row in rows:
        target = primary_by_mod if row.language == language else fallback_by_mod
        if row.mod_id not in target:
            target[row.mod_id] = row.content
    for mod_id, content in fallback_by_mod.items():
        primary_by_mod.setdefault(mod_id, content)
    return primary_by_mod


def load_preferred_brief_summary_map(
    session: Session,
    mod_ids: list[int],
    language: str | None = None,
) -> dict[int, str]:
    """加载配置或持久化数据。"""
    preferred_language = language or SettingsService(session).get("summary_language") or "zh-CN"
    fallback_language = "en" if preferred_language != "en" else None
    return load_summary_map(
        session,
        mod_ids,
        preferred_language,
        "brief",
        fallback_language=fallback_language,
    )


def _is_chinese_language(language: str) -> bool:
    return language.strip().lower().replace("_", "-").startswith("zh")


def _strip_json_fence(content: str) -> str:
    value = content.strip()
    if value.startswith("```"):
        lines = value.splitlines()
        if lines:
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines).strip()
    return value


def _parse_brief_translation_response(content: str) -> tuple[str | None, str]:
    """Return translated title and summary from the LLM brief translation response."""
    value = _strip_json_fence(content)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return None, content.strip()
    if not isinstance(parsed, dict):
        return None, content.strip()

    raw_title = (
        parsed.get("translated_title_zh")
        or parsed.get("translated_title")
        or parsed.get("title_zh")
        or parsed.get("title")
    )
    raw_summary = (
        parsed.get("translated_summary")
        or parsed.get("summary")
        or parsed.get("content")
    )
    translated_title = str(raw_title).strip() if raw_title is not None else None
    translated_summary = str(raw_summary).strip() if raw_summary is not None else ""
    return translated_title or None, translated_summary or content.strip()


class SummaryService:
    """Service for generating AI-powered mod summaries."""

    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    def _get_provider_chain(self) -> list[dict]:
        """读取内部状态或派生结果。"""
        return get_provider_chain(SettingsService(self.session))

    async def generate_summary(
        self,
        mod_id: int,
        language: str = "en",
        summary_type: str = "brief",
        extra_context: str | None = None,
    ) -> dict:
        """Generate an AI summary for a mod.

        Args:
            mod_id: The mod to summarize.
            language: Target language code (en, zh, etc.).
            summary_type: One of 'brief', 'changelog', 'category_guess'.
            extra_context: Optional additional text to include in the prompt.
        """
        mod = None
        try:
            mod = self.session.get(Mod, mod_id)
            if mod is None:
                raise ValueError(f"Mod with id {mod_id} not found")

            chinese_brief = summary_type == "brief" and _is_chinese_language(language)
            brief_prompt = (
                "Translate this mod title and summary into Simplified Chinese. "
                "Keep the meaning, do not add facts. Keep the summary under 200 Chinese characters. "
                "Return only compact JSON with exactly these keys: "
                '{"translated_title_zh":"...","translated_summary":"..."}.\n'
                f"Title: {mod.title}\n"
                f"Summary: {mod.original_summary or mod.title}"
            ) if chinese_brief else (
                f"Translate this mod summary into {language}. "
                f"Title: {mod.title}. "
                f"Summary: {mod.original_summary or mod.title}. "
                "Keep the meaning, do not add facts, and keep under 200 chars. "
                "Return only the translated summary, with no explanation."
            )
            prompts = {
                "brief": brief_prompt,
                "changelog": (
                    f"Summarize this mod's changelog in {language}. Be concise. "
                    f"{extra_context or ''}"
                ),
                "introduction": (
                    f"Write a useful, detailed introduction for this mod in {language}. "
                    "Cover what the mod appears to do, likely use cases, compatibility or setup notes that can be inferred, "
                    "and what a player should verify before installing. Do not invent facts. "
                    "Use concise paragraphs and bullet points when helpful.\n"
                    f"Title: {mod.title}\n"
                    f"Game: {mod.game}\n"
                    f"Author: {mod.author or 'unknown'}\n"
                    f"Version: {mod.version or 'unknown'}\n"
                    f"Original summary: {mod.original_summary or mod.title}\n"
                    f"Source URL: {mod.url}"
                ),
                "category_guess": (
                    "Based on this mod's description, guess the best category tag "
                    "(e.g. Weapons, Armor, Gameplay, Visuals, etc). "
                    "Return only the category name.\n"
                    f"Description: {extra_context or mod.original_summary or ''}"
                ),
            }

            prompt = prompts.get(summary_type, prompts["brief"])
            mod_original_summary = mod.original_summary or ""
            self.session.rollback()

            content = ""
            llm_model = "none"
            for provider_config in self._get_provider_chain():
                llm_provider, llm_api_key, llm_base_url, llm_model = resolve_provider_config(provider_config)

                if not provider_config_has_credentials(provider_config):
                    logger.info("Skipping LLM provider %s because API key is empty", llm_provider)
                    continue

                client = create_llm_client(llm_provider, llm_api_key, llm_base_url)
                try:
                    content = await asyncio.wait_for(
                        client.chat(prompt, llm_model, max_tokens=1024),
                        timeout=SUMMARY_LLM_TIMEOUT_SECONDS,
                    )
                except TimeoutError:
                    logger.warning("LLM provider %s timed out while generating summary", llm_provider)
                    content = ""
                if content:
                    break
                logger.warning("LLM provider %s returned empty content; trying next provider", llm_provider)

            if not content:
                fallback = mod_original_summary
                return {"content": fallback, "model": llm_model}

            translated_title_zh: str | None = None
            if chinese_brief:
                translated_title_zh, content = _parse_brief_translation_response(content)

            existing = self.session.exec(
                select(ModSummary).where(
                    ModSummary.mod_id == mod_id,
                    ModSummary.language == language,
                    ModSummary.summary_type == summary_type,
                )
            ).first()

            if existing:
                existing.content = content
                existing.model = llm_model
                existing.generated_at = datetime.now(UTC).isoformat()
            else:
                summary = ModSummary(
                    mod_id=mod_id,
                    language=language,
                    summary_type=summary_type,
                    content=content,
                    model=llm_model,
                    generated_at=datetime.now(UTC).isoformat(),
                )
                self.session.add(summary)

            if chinese_brief and translated_title_zh:
                current_mod = self.session.get(Mod, mod_id)
                if current_mod is not None:
                    current_mod.translated_title_zh = translated_title_zh[:512]
                    self.session.add(current_mod)

            self.session.commit()
            return {"content": content, "model": llm_model, "translated_title_zh": translated_title_zh}

        except Exception as e:
            logger.error(f"Failed to generate summary for mod {mod_id}: {e}")
            self.session.rollback()
            fallback = mod.original_summary if mod else ""
            return {"content": fallback or "", "model": "error"}

    async def summarize_changelog(
        self, mod_id: int, raw_changelog: str
    ) -> dict:
        """Summarize a raw changelog into a concise summary."""
        return await self.generate_summary(
            mod_id,
            language="en",
            summary_type="changelog",
            extra_context=raw_changelog,
        )

    async def guess_category(
        self, mod_id: int, description: str
    ) -> dict:
        """Guess the mod category from its description text."""
        return await self.generate_summary(
            mod_id,
            language="en",
            summary_type="category_guess",
            extra_context=description,
        )

    async def generate_missing_summaries(
        self,
        mod_ids: list[int] | None = None,
        language: str | None = None,
        max_items: int | None = None,
    ) -> int:
        """Batch-generate summaries for mods that don't have them yet.

        Returns the number of summaries generated.
        """
        if not language:
            language = SettingsService(self.session).get("summary_language") or "zh-CN"

        subquery = select(ModSummary.mod_id).where(
            ModSummary.summary_type == "brief",
            ModSummary.language == language,
        )
        stmt = select(Mod).where(~Mod.id.in_(subquery))
        if mod_ids is not None:
            if not mod_ids:
                return 0
            stmt = stmt.where(Mod.id.in_(mod_ids))
        stmt = stmt.order_by(Mod.id)
        if max_items is not None:
            if max_items <= 0:
                return 0
            stmt = stmt.limit(max_items)
        mods_missing = self.session.exec(stmt).all()
        mod_ids_missing = [mod.id for mod in mods_missing if mod.id is not None]
        self.session.rollback()

        count = 0
        for mod_id in mod_ids_missing:
            result = await self.generate_summary(
                mod_id, language=language, summary_type="brief"
            )
            if result.get("model") not in ("error", "none"):
                count += 1

        return count
