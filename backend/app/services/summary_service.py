import asyncio
import logging
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.jobs.tracked_jobs import run_tracked_job
from app.services.llm_client import DEFAULT_MODELS, create_llm_client
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)
SUMMARY_GENERATION_LOCK = asyncio.Lock()


def load_summary_map(
    session: Session,
    mod_ids: list[int],
    language: str,
    summary_type: str,
) -> dict[int, str]:
    if not mod_ids:
        return {}
    rows = session.exec(
        select(ModSummary).where(
            ModSummary.mod_id.in_(mod_ids),
            ModSummary.language == language,
            ModSummary.summary_type == summary_type,
        )
    ).all()
    return {row.mod_id: row.content for row in rows}


async def run_missing_summaries_job(mod_ids: list[int], language: str) -> None:
    if SUMMARY_GENERATION_LOCK.locked():
        return
    async with SUMMARY_GENERATION_LOCK:
        async def handler(session: Session) -> dict:
            service = SummaryService(session)
            count = await service.generate_missing_summaries(
                mod_ids=mod_ids,
                language=language,
            )
            return {
                "items_scanned": len(mod_ids),
                "items_matched": count,
                "generated": count,
                "language": language,
                "mod_ids": mod_ids,
            }

        await run_tracked_job(
            "llm_translate_summaries",
            handler,
            metadata={"language": language, "mod_ids": mod_ids},
        )


async def run_single_summary_job(
    mod_id: int,
    language: str,
    summary_type: str,
) -> None:
    async def handler(session: Session) -> dict:
        service = SummaryService(session)
        result = await service.generate_summary(
            mod_id,
            language=language,
            summary_type=summary_type,
        )
        generated = 1 if result.get("model") not in ("error", "none") else 0
        return {
            "items_scanned": 1,
            "items_matched": generated,
            "mod_id": mod_id,
            "language": language,
            "summary_type": summary_type,
            "model": result.get("model"),
        }

    await run_tracked_job(
        f"llm_{'regenerate_summary' if summary_type == 'brief' else 'generate_introduction'}",
        handler,
        metadata={
            "mod_id": mod_id,
            "language": language,
            "summary_type": summary_type,
        },
    )


class SummaryService:
    """Service for generating AI-powered mod summaries."""

    def __init__(self, session: Session):
        self.session = session

    def _get_provider_chain(self) -> list[dict]:
        settings_svc = SettingsService(self.session)
        raw = settings_svc.get("llm_providers_json") or ""
        providers: list[dict] = []
        if raw:
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list):
                    providers = [p for p in parsed if isinstance(p, dict) and p.get("enabled")]
            except json.JSONDecodeError:
                logger.warning("Invalid llm_providers_json; falling back to legacy LLM settings")

        if not providers:
            providers = [
                {
                    "provider": settings_svc.get("llm_provider") or "openai",
                    "model": settings_svc.get("llm_model") or "",
                    "api_key": settings_svc.get("llm_api_key") or "",
                    "base_url": settings_svc.get("llm_base_url") or "",
                    "priority": 1,
                }
            ]

        return sorted(providers, key=lambda p: int(p.get("priority") or 999))

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

            prompts = {
                "brief": (
                    f"Translate this mod summary into {language}. "
                    f"Title: {mod.title}. "
                    f"Summary: {mod.original_summary or mod.title}. "
                    "Keep the meaning, do not add facts, and keep under 200 chars. "
                    "Return only the translated summary, with no explanation."
                ),
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
                llm_provider = str(provider_config.get("provider") or "openai")
                llm_api_key = str(provider_config.get("api_key") or "")
                llm_model = str(provider_config.get("model") or "") or DEFAULT_MODELS.get(llm_provider, "gpt-4o-mini")
                llm_base_url = str(provider_config.get("base_url") or "")

                if not llm_api_key and llm_provider != "ollama":
                    logger.info("Skipping LLM provider %s because API key is empty", llm_provider)
                    continue

                client = create_llm_client(llm_provider, llm_api_key, llm_base_url)
                content = await client.chat(prompt, llm_model, max_tokens=1024)
                if content:
                    break
                logger.warning("LLM provider %s returned empty content; trying next provider", llm_provider)

            if not content:
                fallback = mod_original_summary
                return {"content": fallback, "model": llm_model}

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
                existing.generated_at = datetime.now(timezone.utc).isoformat()
            else:
                summary = ModSummary(
                    mod_id=mod_id,
                    language=language,
                    summary_type=summary_type,
                    content=content,
                    model=llm_model,
                    generated_at=datetime.now(timezone.utc).isoformat(),
                )
                self.session.add(summary)

            self.session.commit()
            return {"content": content, "model": llm_model}

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
