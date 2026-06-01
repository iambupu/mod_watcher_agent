import asyncio
import logging
import re
from collections.abc import Callable
from datetime import UTC, datetime
from time import perf_counter

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
from app.utils.json import json_object_from_text
from app.utils.numeric import safe_nonnegative_int

logger = logging.getLogger(__name__)
SUMMARY_GENERATION_LOCK = asyncio.Lock()
SUMMARY_LLM_TIMEOUT_SECONDS = 60.0
SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS = 20.0
SUMMARY_DEFAULT_MAX_TOKENS = 1024
SUMMARY_BRIEF_MAX_TOKENS = 384
SUMMARY_BRIEF_REASONING_RETRY_MAX_TOKENS = 1024
SUMMARY_LOOKUP_BATCH_SIZE = 800


def _batched(items: list, size: int):
    for index in range(0, len(items), size):
        yield items[index:index + size]


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
    rows: list[ModSummary] = []
    for mod_id_batch in _batched(mod_ids, SUMMARY_LOOKUP_BATCH_SIZE):
        rows.extend(
            session.exec(
                select(ModSummary)
                .where(
                    ModSummary.mod_id.in_(mod_id_batch),
                    ModSummary.language.in_(languages),
                    ModSummary.summary_type == summary_type,
                )
                .order_by(ModSummary.id.desc())
            ).all()
        )
    primary_by_mod: dict[int, str] = {}
    fallback_by_mod: dict[int, str] = {}
    for row in rows:
        if not _summary_matches_requested_language(row.content, row.language):
            continue
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
    *,
    fallback_language: str | None = None,
) -> dict[int, str]:
    """加载配置或持久化数据。"""
    preferred_language = language or SettingsService(session).get("summary_language") or "zh-CN"
    return load_summary_map(
        session,
        mod_ids,
        preferred_language,
        "brief",
        fallback_language=fallback_language,
    )


def _is_chinese_language(language: str) -> bool:
    return language.strip().lower().replace("_", "-").startswith("zh")


def _contains_cjk(value: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in value)


def _summary_matches_requested_language(content: str | None, language: str) -> bool:
    value = str(content or "").strip()
    if not value:
        return False
    if _is_chinese_language(language):
        return _contains_cjk(value)
    return True


def _parse_brief_translation_response(content: str) -> tuple[str | None, str]:
    """Return translated title and summary from the LLM brief translation response."""
    parsed = json_object_from_text(content)
    if parsed is None:
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


def _contains_latin(value: str) -> bool:
    return any("A" <= char <= "Z" or "a" <= char <= "z" for char in value)


def _extract_protected_translation_terms(title: str, summary: str) -> list[str]:
    terms: list[str] = []

    def add(term: str) -> None:
        value = term.strip(" -:;,.()[]{}'\"")
        if len(value) < 2 or value.lower() in {"the", "and", "for", "with", "of", "to"}:
            return
        if value not in terms:
            terms.append(value)

    title_head = re.split(r"\s[-–—:|]\s", title.strip(), maxsplit=1)[0].strip()
    if _contains_latin(title_head) and re.search(r"\b(of|for|and|the)\b", title_head, re.IGNORECASE):
        add(title_head)

    for match in re.finditer(r"\b[A-Z][A-Z0-9]{1,}\b", f"{title}\n{summary}"):
        add(match.group(0))

    return terms[:8]


def _missing_protected_terms(value: str, protected_terms: list[str]) -> list[str]:
    haystack = value.lower()
    missing: list[str] = []
    for term in protected_terms:
        key = term.lower()
        if key not in haystack:
            missing.append(term)
    return missing


def _brief_translation_missing_protected_terms(
    *,
    translated_title: str | None,
    translated_summary: str,
    protected_terms: list[str],
) -> list[str]:
    target = f"{translated_title or ''}\n{translated_summary}"
    return _missing_protected_terms(target, protected_terms)


def _build_brief_translation_repair_prompt(
    *,
    title: str,
    summary: str,
    previous_title: str | None,
    previous_summary: str,
    protected_terms: list[str],
) -> str:
    terms = ", ".join(protected_terms)
    return (
        "Fix the Simplified Chinese translation below. "
        "Preserve these exact terms unchanged wherever they appear in the source: "
        f"{terms}. Do not translate, paraphrase, or replace them. "
        "Keep the meaning, do not add facts, and keep the summary under 200 Chinese characters. "
        "Return only compact JSON with exactly these keys: "
        '{"translated_title_zh":"...","translated_summary":"..."}.\n'
        f"Source title: {title}\n"
        f"Source summary: {summary or title}\n"
        f"Previous translated title: {previous_title or ''}\n"
        f"Previous translated summary: {previous_summary}"
    )


def _should_retry_empty_reasoning_response(client) -> bool:
    detail = str(getattr(client, "last_detail", "") or "").lower()
    return bool(detail and "content was empty" in detail and "reasoning" in detail)


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
            mod_original_summary = mod.original_summary or ""
            source_summary = mod_original_summary or mod.title
            protected_terms = (
                _extract_protected_translation_terms(mod.title, mod_original_summary)
                if chinese_brief
                else []
            )
            protected_instruction = (
                "Preserve these exact terms unchanged if they appear: "
                f"{', '.join(protected_terms)}. "
                if protected_terms
                else ""
            )
            brief_prompt = (
                "Answer directly. Do not reason, analyze, explain, or think step by step. "
                "Translate this mod title and summary into Simplified Chinese. "
                "Keep the meaning, do not add facts. Keep the summary under 200 Chinese characters. "
                f"{protected_instruction}"
                "Preserve proper nouns, game names, author names, source names, version strings, and URLs. "
                "Do not use Markdown, code fences, notes, or explanations. "
                "Return only compact JSON with exactly these keys: "
                '{"translated_title_zh":"...","translated_summary":"..."}.\n'
                f"Title: {mod.title}\n"
                f"Summary: {source_summary}"
            ) if chinese_brief else (
                f"Translate this mod summary into {language}. "
                f"Title: {mod.title}. "
                f"Summary: {source_summary}. "
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
            self.session.rollback()

            content = ""
            llm_provider = "none"
            llm_model = "none"
            llm_api_key = ""
            llm_base_url = ""
            translated_title_zh: str | None = None
            last_error = "llm_empty_or_unavailable"
            provider_attempts: list[dict[str, object]] = []
            max_tokens = SUMMARY_BRIEF_MAX_TOKENS if chinese_brief else SUMMARY_DEFAULT_MAX_TOKENS
            request_timeout = (
                SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS
                if chinese_brief
                else SUMMARY_LLM_TIMEOUT_SECONDS
            )
            for provider_config in self._get_provider_chain():
                llm_provider, llm_api_key, llm_base_url, llm_model = resolve_provider_config(provider_config)

                if not provider_config_has_credentials(provider_config):
                    logger.info("Skipping LLM provider %s because API key is empty", llm_provider)
                    last_error = "missing_credentials"
                    provider_attempts.append(
                        {
                            "provider": llm_provider,
                            "model": llm_model,
                            "success": False,
                            "reason": "missing_credentials",
                        }
                    )
                    continue

                client = create_llm_client(llm_provider, llm_api_key, llm_base_url)
                attempt_tokens = max_tokens
                try:
                    started_at = perf_counter()
                    content = await asyncio.wait_for(
                        client.chat(
                            prompt,
                            llm_model,
                            max_tokens=attempt_tokens,
                            request_timeout=request_timeout,
                        ),
                        timeout=request_timeout + 5.0,
                    )
                except TimeoutError:
                    logger.warning("LLM provider %s timed out while generating summary", llm_provider)
                    content = ""
                else:
                    logger.info(
                        "LLM provider %s generated %s summary in %.0fms",
                        llm_provider,
                        summary_type,
                        (perf_counter() - started_at) * 1000,
                    )
                if not content and chinese_brief and _should_retry_empty_reasoning_response(client):
                    attempt_tokens = max(attempt_tokens * 2, SUMMARY_BRIEF_REASONING_RETRY_MAX_TOKENS)
                    logger.warning(
                        "LLM provider %s returned reasoning without final content; retrying with max_tokens=%s",
                        llm_provider,
                        attempt_tokens,
                    )
                    try:
                        started_at = perf_counter()
                        content = await asyncio.wait_for(
                            client.chat(
                                prompt,
                                llm_model,
                                max_tokens=attempt_tokens,
                                request_timeout=request_timeout,
                            ),
                            timeout=request_timeout + 5.0,
                        )
                    except TimeoutError:
                        logger.warning("LLM provider %s timed out while retrying summary", llm_provider)
                        content = ""
                    else:
                        logger.info(
                            "LLM provider %s retried %s summary in %.0fms",
                            llm_provider,
                            summary_type,
                            (perf_counter() - started_at) * 1000,
                        )
                attempt_reason = (
                    "ok"
                    if content
                    else getattr(client, "last_error", "")
                    or getattr(client, "last_detail", "")
                    or "empty_content"
                )
                candidate_title_zh: str | None = None
                if content and chinese_brief:
                    candidate_title_zh, content = _parse_brief_translation_response(content)
                    if not _summary_matches_requested_language(content, language):
                        logger.warning(
                            "LLM provider %s returned non-target-language summary; trying next provider.",
                            llm_provider,
                        )
                        attempt_reason = "target_language_missing"
                        last_error = attempt_reason
                        content = ""
                    else:
                        protected_terms = _extract_protected_translation_terms(
                            mod.title,
                            mod_original_summary,
                        )
                        missing_terms = _brief_translation_missing_protected_terms(
                            translated_title=candidate_title_zh,
                            translated_summary=content,
                            protected_terms=protected_terms,
                        )
                        if missing_terms and llm_provider != "none":
                            repair_prompt = _build_brief_translation_repair_prompt(
                                title=mod.title,
                                summary=mod_original_summary,
                                previous_title=candidate_title_zh,
                                previous_summary=content,
                                protected_terms=protected_terms,
                            )
                            logger.warning(
                                "LLM provider %s changed protected translation terms; repairing summary. missing_terms=%s",
                                llm_provider,
                                missing_terms,
                            )
                            repair_client = create_llm_client(llm_provider, llm_api_key, llm_base_url)
                            try:
                                repair_content = await asyncio.wait_for(
                                    repair_client.chat(
                                        repair_prompt,
                                        llm_model,
                                        max_tokens=SUMMARY_BRIEF_MAX_TOKENS,
                                        request_timeout=SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS,
                                    ),
                                    timeout=SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS + 5.0,
                                )
                            except TimeoutError:
                                repair_content = ""
                            if repair_content:
                                repaired_title, repaired_summary = _parse_brief_translation_response(repair_content)
                                repaired_missing = _brief_translation_missing_protected_terms(
                                    translated_title=repaired_title,
                                    translated_summary=repaired_summary,
                                    protected_terms=protected_terms,
                                )
                                if not repaired_missing and _summary_matches_requested_language(
                                    repaired_summary,
                                    language,
                                ):
                                    candidate_title_zh = repaired_title
                                    content = repaired_summary
                                    missing_terms = []

                        if missing_terms:
                            logger.warning(
                                "LLM provider %s could not preserve protected translation terms; trying next provider. missing_terms=%s",
                                llm_provider,
                                missing_terms,
                            )
                            attempt_reason = "protected_terms_missing"
                            last_error = attempt_reason
                            content = ""

                provider_attempts.append(
                    {
                        "provider": llm_provider,
                        "model": llm_model,
                        "success": bool(content),
                        "reason": "ok" if content else attempt_reason,
                        "max_tokens": attempt_tokens,
                    }
                )
                if content:
                    translated_title_zh = candidate_title_zh
                    break
                logger.warning("LLM provider %s did not produce an acceptable summary; trying next provider", llm_provider)

            if not content:
                return {
                    "content": "",
                    "model": "none",
                    "provider": llm_provider,
                    "error": last_error,
                    "provider_attempts": provider_attempts,
                }

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
            return {
                "content": content,
                "model": llm_model,
                "provider": llm_provider,
                "translated_title_zh": translated_title_zh,
                "provider_attempts": provider_attempts,
            }

        except Exception as e:
            logger.error(f"Failed to generate summary for mod {mod_id}: {e}")
            self.session.rollback()
            fallback = mod.original_summary if mod else ""
            return {"content": fallback or "", "model": "error", "provider": "error", "provider_attempts": []}

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
        report = await self.generate_missing_summaries_report(
            mod_ids=mod_ids,
            language=language,
            max_items=max_items,
        )
        return safe_nonnegative_int(report.get("generated", 0))

    async def generate_missing_summaries_report(
        self,
        mod_ids: list[int] | None = None,
        language: str | None = None,
        max_items: int | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> dict:
        """Generate missing or invalid summaries and return scanned/generated details."""
        if not language:
            language = SettingsService(self.session).get("summary_language") or "zh-CN"

        stmt = select(Mod)
        if mod_ids is not None:
            if not mod_ids:
                return {"scanned": 0, "generated": 0, "failed": 0, "failures": [], "mod_ids": []}
            stmt = stmt.where(Mod.id.in_(mod_ids))
        if max_items is not None and max_items <= 0:
            return {"scanned": 0, "generated": 0, "failed": 0, "failures": [], "mod_ids": []}

        stmt = stmt.order_by(Mod.id)
        mods = self.session.exec(stmt).all()
        mods_missing: list[Mod] = []
        for mod_batch in _batched(mods, SUMMARY_LOOKUP_BATCH_SIZE):
            mod_ids_batch = [mod.id for mod in mod_batch if mod.id is not None]
            valid_summary_by_mod = load_summary_map(self.session, mod_ids_batch, language, "brief")
            for mod in mod_batch:
                if (
                    mod.id is not None
                    and mod.id not in valid_summary_by_mod
                    and (mod.original_summary or mod.title)
                ):
                    mods_missing.append(mod)
                    if max_items is not None and len(mods_missing) >= max_items:
                        break
            if max_items is not None and len(mods_missing) >= max_items:
                break
        mod_ids_missing = [mod.id for mod in mods_missing if mod.id is not None]
        self.session.rollback()

        count = 0
        failures: list[dict] = []
        for mod_id in mod_ids_missing:
            if should_stop is not None and should_stop():
                break
            result = await self.generate_summary(
                mod_id, language=language, summary_type="brief"
            )
            if result.get("model") not in ("error", "none") and not result.get("error"):
                count += 1
            else:
                failures.append(
                    {
                        "mod_id": mod_id,
                        "provider": result.get("provider"),
                        "model": result.get("model"),
                        "error": result.get("error") or "summary_not_generated",
                        "provider_attempts": result.get("provider_attempts") or [],
                    }
                )

        return {
            "scanned": len(mod_ids_missing),
            "generated": count,
            "failed": len(failures),
            "failures": failures,
            "mod_ids": mod_ids_missing,
        }
