import asyncio
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import perf_counter
from weakref import WeakKeyDictionary

from sqlalchemy import func, or_
from sqlalchemy.orm import aliased
from sqlmodel import Session, select

from app.models.mod import Mod
from app.models.summary import ModSummary
from app.services.llm_client import LLMClient, create_llm_client
from app.services.llm_provider_config import (
    get_provider_chain,
    provider_config_has_credentials,
    resolve_provider_config,
)
from app.services.settings_service import SettingsService
from app.utils.json import json_object_from_text, strip_json_fence
from app.utils.numeric import safe_nonnegative_int

logger = logging.getLogger(__name__)


class LoopLocalAsyncLock:
    def __init__(self) -> None:
        self._locks: WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Lock] = WeakKeyDictionary()

    def _current_lock(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        lock = self._locks.get(loop)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[loop] = lock
        return lock

    def locked(self) -> bool:
        return self._current_lock().locked()

    async def acquire(self) -> bool:
        return await self._current_lock().acquire()

    def release(self) -> None:
        self._current_lock().release()

    async def __aenter__(self):
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        self.release()


SUMMARY_GENERATION_LOCK = LoopLocalAsyncLock()
SUMMARY_BATCH_LOCK = LoopLocalAsyncLock()
SUMMARY_LLM_TIMEOUT_SECONDS = 60.0
SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS = 20.0
SUMMARY_DEFAULT_MAX_TOKENS = 1024
SUMMARY_BRIEF_MAX_TOKENS = 384
SUMMARY_BRIEF_REASONING_RETRY_MAX_TOKENS = 1024
SUMMARY_LOOKUP_BATCH_SIZE = 800
BRIEF_TRANSLATION_TITLE_KEYS = ("translated_title_zh", "translated_title", "title_zh", "title")
BRIEF_TRANSLATION_SUMMARY_KEYS = (
    "translated_summary",
    "translated_summary_zh",
    "summary_zh",
    "summary",
    "content",
)


@dataclass(frozen=True)
class _SummaryRequest:
    mod_id: int
    language: str
    summary_type: str
    prompt: str
    chinese_brief: bool
    original_summary: str
    max_tokens: int
    request_timeout: float


@dataclass
class _ProviderGeneration:
    content: str = ""
    provider: str = "none"
    model: str = "none"
    api_key: str = ""
    base_url: str = ""
    translated_title_zh: str | None = None
    last_error: str = "llm_empty_or_unavailable"
    attempts: list[dict[str, object]] = field(default_factory=list)


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
    """读取首选语言的 brief 摘要，必要时使用 fallback 语言。"""
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
        content = _normalize_summary_content(row.content, row.language, row.summary_type)
        if _looks_like_unparsed_brief_translation_payload(content):
            continue
        if not _summary_matches_requested_language(content, row.language):
            continue
        target = primary_by_mod if row.language == language else fallback_by_mod
        if row.mod_id not in target:
            target[row.mod_id] = content
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
    """批量读取指定语言和类型的摘要，并按语言规则过滤异常内容。"""
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


def _normalize_summary_content(content: str | None, language: str, summary_type: str) -> str:
    value = str(content or "").strip()
    if summary_type == "brief" and _is_chinese_language(language):
        _translated_title, translated_summary = _parse_brief_translation_response(value)
        return translated_summary.strip()
    return value


def _looks_like_unparsed_brief_translation_payload(content: str | None) -> bool:
    value = strip_json_fence(content).lstrip()
    if not value.startswith("{"):
        return False
    return any(
        key in value
        for key in (*BRIEF_TRANSLATION_TITLE_KEYS, *BRIEF_TRANSLATION_SUMMARY_KEYS)
    )


def _parse_brief_translation_response(content: str) -> tuple[str | None, str]:
    """Return translated title and summary from the LLM brief translation response."""
    parsed = json_object_from_text(content)
    raw_title = _text_from_payload_keys(parsed, BRIEF_TRANSLATION_TITLE_KEYS)
    raw_summary = _text_from_payload_keys(parsed, BRIEF_TRANSLATION_SUMMARY_KEYS)
    if raw_title is None:
        raw_title = _extract_json_like_field(content, BRIEF_TRANSLATION_TITLE_KEYS)
    if raw_summary is None:
        raw_summary = _extract_json_like_field(content, BRIEF_TRANSLATION_SUMMARY_KEYS)

    translated_title = raw_title.strip() if raw_title is not None else None
    translated_summary = raw_summary.strip() if raw_summary is not None else ""
    return translated_title or None, translated_summary or content.strip()


def _text_from_payload_keys(
    parsed: dict[str, object] | None,
    keys: tuple[str, ...],
) -> str | None:
    if not parsed:
        return None
    for key in keys:
        raw_value = parsed.get(key)
        if raw_value is None:
            continue
        value = str(raw_value).strip()
        if value:
            return value
    return None


def _extract_json_like_field(content: str, keys: tuple[str, ...]) -> str | None:
    raw = strip_json_fence(content)
    for key in keys:
        match = re.search(rf"(?<![A-Za-z0-9_])[\"'“”]?{re.escape(key)}[\"'“”]?\s*:", raw)
        if not match:
            continue
        value = _read_json_like_value(raw[match.end():])
        if value:
            return value
    return None


def _read_json_like_value(raw_value: str) -> str:
    value = raw_value.lstrip()
    if not value:
        return ""
    quote_pairs = {'"': '"', "'": "'", "“": "”", "”": "”"}
    if value[0] in quote_pairs:
        return _read_json_like_quoted_value(value, quote_pairs[value[0]])
    return _clean_json_like_scalar(re.split(r"[,}]", value, maxsplit=1)[0])


def _read_json_like_quoted_value(value: str, closing_quote: str) -> str:
    chars: list[str] = []
    escaped = False
    for index, char in enumerate(value[1:], start=1):
        if escaped:
            chars.append(char)
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == closing_quote:
            tail = value[index + 1:].lstrip()
            if not tail or tail[0] in ",}":
                return _clean_json_like_scalar("".join(chars))
        chars.append(char)
    return _clean_json_like_scalar("".join(chars))


def _clean_json_like_scalar(value: str) -> str:
    return value.strip().removesuffix("}").strip().strip("\"'“”").strip()


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


def _summary_prompt(
    mod: Mod,
    *,
    language: str,
    summary_type: str,
    extra_context: str | None,
    chinese_brief: bool,
    original_summary: str,
) -> str:
    source_summary = original_summary or mod.title
    protected_terms = (
        _extract_protected_translation_terms(mod.title, original_summary)
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
        if chinese_brief
        else (
            f"Translate this mod summary into {language}. "
            f"Title: {mod.title}. "
            f"Summary: {source_summary}. "
            "Keep the meaning, do not add facts, and keep under 200 chars. "
            "Return only the translated summary, with no explanation."
        )
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
    return prompts.get(summary_type, brief_prompt)


def _provider_attempt_reason(client: LLMClient, content: str) -> str:
    return "ok" if content else client.last_error or client.last_detail or "empty_content"


async def _timed_summary_chat(
    client: LLMClient,
    *,
    prompt: str,
    model: str,
    max_tokens: int,
    request_timeout: float,
    provider: str,
    summary_type: str,
    action: str,
    log_timeout: bool = True,
) -> str:
    try:
        started_at = perf_counter()
        content = await asyncio.wait_for(
            client.chat(
                prompt,
                model,
                max_tokens=max_tokens,
                request_timeout=request_timeout,
            ),
            timeout=request_timeout + 5.0,
        )
    except TimeoutError:
        if log_timeout:
            timeout_action = "retrying" if action == "retried" else "generating"
            logger.warning(
                "LLM provider %s timed out while %s summary", provider, timeout_action
            )
        return ""
    logger.info(
        "LLM provider %s %s %s summary in %.0fms",
        provider,
        action,
        summary_type,
        (perf_counter() - started_at) * 1000,
    )
    return content


def _upsert_summary_record(
    session: Session,
    *,
    existing: ModSummary | None,
    request: _SummaryRequest,
    generated: _ProviderGeneration,
) -> bool:
    now = datetime.now(UTC).isoformat()
    if existing is None:
        session.add(
            ModSummary(
                mod_id=request.mod_id,
                language=request.language,
                summary_type=request.summary_type,
                content=generated.content,
                model=generated.model,
                generated_at=now,
            )
        )
        return True
    changed = False
    if existing.content != generated.content:
        existing.content = generated.content
        changed = True
    if existing.model != generated.model:
        existing.model = generated.model
        changed = True
    if changed:
        existing.generated_at = now
    return changed


class SummaryService:
    """Service for generating AI-powered mod summaries."""

    def __init__(self, session: Session):
        """保存数据库会话，用于读取 Mod、调用 LLM 并写入摘要。"""
        self.session = session

    def _get_provider_chain(self) -> list[dict]:
        """读取当前设置中的 LLM provider 调用顺序。"""
        return get_provider_chain(SettingsService(self.session))

    async def generate_summary(
        self,
        mod_id: int,
        language: str = "en",
        summary_type: str = "brief",
        extra_context: str | None = None,
    ) -> dict:
        """Generate and persist an AI summary through the configured provider chain."""
        mod = None
        try:
            mod = self.session.get(Mod, mod_id)
            if mod is None:
                raise ValueError(f"Mod with id {mod_id} not found")
            request = self._build_summary_request(
                mod,
                language=language,
                summary_type=summary_type,
                extra_context=extra_context,
            )
            provider_chain = self._get_provider_chain()
            self.session.rollback()
            generated = await self._generate_from_provider_chain(request, mod, provider_chain)
            if not generated.content:
                return {
                    "content": "",
                    "model": "none",
                    "provider": generated.provider,
                    "error": generated.last_error,
                    "provider_attempts": generated.attempts,
                }
            self._persist_generated_summary(request, generated)
            return {
                "content": generated.content,
                "model": generated.model,
                "provider": generated.provider,
                "translated_title_zh": generated.translated_title_zh,
                "provider_attempts": generated.attempts,
            }
        except Exception as e:
            logger.error("Failed to generate summary for mod %s: %s", mod_id, e)
            self.session.rollback()
            fallback = mod.original_summary if mod else ""
            return {
                "content": fallback or "",
                "model": "error",
                "provider": "error",
                "provider_attempts": [],
            }

    def _build_summary_request(
        self,
        mod: Mod,
        *,
        language: str,
        summary_type: str,
        extra_context: str | None,
    ) -> _SummaryRequest:
        chinese_brief = summary_type == "brief" and _is_chinese_language(language)
        original_summary = mod.original_summary or ""
        prompt = _summary_prompt(
            mod,
            language=language,
            summary_type=summary_type,
            extra_context=extra_context,
            chinese_brief=chinese_brief,
            original_summary=original_summary,
        )
        return _SummaryRequest(
            mod_id=int(mod.id or 0),
            language=language,
            summary_type=summary_type,
            prompt=prompt,
            chinese_brief=chinese_brief,
            original_summary=original_summary,
            max_tokens=SUMMARY_BRIEF_MAX_TOKENS if chinese_brief else SUMMARY_DEFAULT_MAX_TOKENS,
            request_timeout=(
                SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS
                if chinese_brief
                else SUMMARY_LLM_TIMEOUT_SECONDS
            ),
        )

    async def _generate_from_provider_chain(
        self,
        request: _SummaryRequest,
        mod: Mod,
        provider_chain: list[dict],
    ) -> _ProviderGeneration:
        result = _ProviderGeneration()
        for provider_config in provider_chain:
            result.provider, result.api_key, result.base_url, result.model = resolve_provider_config(
                provider_config
            )
            if not provider_config_has_credentials(provider_config):
                self._record_missing_provider_credentials(result)
                continue
            client = create_llm_client(result.provider, result.api_key, result.base_url)
            content, attempt_tokens = await self._request_provider_summary(
                request, client, result.provider, result.model
            )
            attempt_reason = _provider_attempt_reason(client, content)
            candidate_title: str | None = None
            if content and request.chinese_brief:
                candidate_title, content, attempt_reason = await self._validate_brief_translation(
                    request,
                    mod,
                    result,
                    candidate_title,
                    content,
                )
            result.attempts.append(
                {
                    "provider": result.provider,
                    "model": result.model,
                    "success": bool(content),
                    "reason": "ok" if content else attempt_reason,
                    "max_tokens": attempt_tokens,
                }
            )
            if content:
                result.content = content
                result.translated_title_zh = candidate_title
                break
            logger.warning(
                "LLM provider %s did not produce an acceptable summary; trying next provider",
                result.provider,
            )
        return result

    def _record_missing_provider_credentials(self, result: _ProviderGeneration) -> None:
        logger.info("Skipping LLM provider %s because API key is empty", result.provider)
        result.last_error = "missing_credentials"
        result.attempts.append(
            {
                "provider": result.provider,
                "model": result.model,
                "success": False,
                "reason": "missing_credentials",
            }
        )

    async def _request_provider_summary(
        self,
        request: _SummaryRequest,
        client: object,
        provider: str,
        model: str,
    ) -> tuple[str, int]:
        content = await _timed_summary_chat(
            client,
            prompt=request.prompt,
            model=model,
            max_tokens=request.max_tokens,
            request_timeout=request.request_timeout,
            provider=provider,
            summary_type=request.summary_type,
            action="generated",
        )
        attempt_tokens = request.max_tokens
        if not content and request.chinese_brief and _should_retry_empty_reasoning_response(client):
            attempt_tokens = max(
                attempt_tokens * 2, SUMMARY_BRIEF_REASONING_RETRY_MAX_TOKENS
            )
            logger.warning(
                "LLM provider %s returned reasoning without final content; retrying with max_tokens=%s",
                provider,
                attempt_tokens,
            )
            content = await _timed_summary_chat(
                client,
                prompt=request.prompt,
                model=model,
                max_tokens=attempt_tokens,
                request_timeout=request.request_timeout,
                provider=provider,
                summary_type=request.summary_type,
                action="retried",
            )
        return content, attempt_tokens

    async def _validate_brief_translation(
        self,
        request: _SummaryRequest,
        mod: Mod,
        result: _ProviderGeneration,
        candidate_title: str | None,
        content: str,
    ) -> tuple[str | None, str, str]:
        candidate_title, content = _parse_brief_translation_response(content)
        if not _summary_matches_requested_language(content, request.language):
            logger.warning(
                "LLM provider %s returned non-target-language summary; trying next provider.",
                result.provider,
            )
            result.last_error = "target_language_missing"
            return candidate_title, "", result.last_error
        protected_terms = _extract_protected_translation_terms(
            mod.title, request.original_summary
        )
        missing_terms = _brief_translation_missing_protected_terms(
            translated_title=candidate_title,
            translated_summary=content,
            protected_terms=protected_terms,
        )
        if missing_terms and result.provider != "none":
            candidate_title, content, missing_terms = await self._repair_brief_translation(
                request,
                mod,
                result,
                candidate_title,
                content,
                protected_terms,
                missing_terms,
            )
        if missing_terms:
            logger.warning(
                "LLM provider %s could not preserve protected translation terms; trying next provider. missing_terms=%s",
                result.provider,
                missing_terms,
            )
            result.last_error = "protected_terms_missing"
            return candidate_title, "", result.last_error
        return candidate_title, content, "ok"

    async def _repair_brief_translation(
        self,
        request: _SummaryRequest,
        mod: Mod,
        result: _ProviderGeneration,
        candidate_title: str | None,
        content: str,
        protected_terms: list[str],
        missing_terms: list[str],
    ) -> tuple[str | None, str, list[str]]:
        logger.warning(
            "LLM provider %s changed protected translation terms; repairing summary. missing_terms=%s",
            result.provider,
            missing_terms,
        )
        repair_client = create_llm_client(result.provider, result.api_key, result.base_url)
        repair_content = await _timed_summary_chat(
            repair_client,
            prompt=_build_brief_translation_repair_prompt(
                title=mod.title,
                summary=request.original_summary,
                previous_title=candidate_title,
                previous_summary=content,
                protected_terms=protected_terms,
            ),
            model=result.model,
            max_tokens=SUMMARY_BRIEF_MAX_TOKENS,
            request_timeout=SUMMARY_BRIEF_LLM_TIMEOUT_SECONDS,
            provider=result.provider,
            summary_type=request.summary_type,
            action="repaired",
            log_timeout=False,
        )
        if not repair_content:
            return candidate_title, content, missing_terms
        repaired_title, repaired_summary = _parse_brief_translation_response(repair_content)
        repaired_missing = _brief_translation_missing_protected_terms(
            translated_title=repaired_title,
            translated_summary=repaired_summary,
            protected_terms=protected_terms,
        )
        if repaired_missing or not _summary_matches_requested_language(
            repaired_summary, request.language
        ):
            return candidate_title, content, missing_terms
        return repaired_title, repaired_summary, []

    def _persist_generated_summary(
        self,
        request: _SummaryRequest,
        generated: _ProviderGeneration,
    ) -> None:
        existing = self.session.exec(
            select(ModSummary).where(
                ModSummary.mod_id == request.mod_id,
                ModSummary.language == request.language,
                ModSummary.summary_type == request.summary_type,
            )
        ).first()
        changed = _upsert_summary_record(
            self.session,
            existing=existing,
            request=request,
            generated=generated,
        )
        if request.chinese_brief and generated.translated_title_zh:
            changed = self._update_translated_mod_title(request, generated) or changed
        if changed:
            self.session.commit()
        else:
            self.session.rollback()

    def _update_translated_mod_title(
        self,
        request: _SummaryRequest,
        generated: _ProviderGeneration,
    ) -> bool:
        current_mod = self.session.get(Mod, request.mod_id)
        if current_mod is None:
            return False
        next_title = str(generated.translated_title_zh or "")[:512]
        if current_mod.translated_title_zh == next_title:
            return False
        current_mod.translated_title_zh = next_title
        self.session.add(current_mod)
        return True

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

        if max_items is not None and max_items <= 0:
            return {"scanned": 0, "generated": 0, "failed": 0, "failures": [], "mod_ids": []}

        mod_ids_missing = self._summary_refresh_candidate_ids(
            language=language,
            mod_ids=mod_ids,
            max_items=max_items,
        )
        self.session.rollback()

        count = 0
        failures: list[dict] = []
        for mod_id in mod_ids_missing:
            if should_stop is not None and should_stop():
                break
            async with SUMMARY_GENERATION_LOCK:
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

    def _summary_refresh_candidate_ids(
        self,
        *,
        language: str,
        mod_ids: list[int] | None,
        max_items: int | None,
    ) -> list[int]:
        """Return mods that need a brief summary without loading the full mods table."""
        if mod_ids is not None and not mod_ids:
            return []

        latest_summary_ids = (
            select(
                ModSummary.mod_id,
                func.max(ModSummary.id).label("latest_summary_id"),
            )
            .where(
                ModSummary.language == language,
                ModSummary.summary_type == "brief",
            )
            .group_by(ModSummary.mod_id)
            .subquery()
        )
        latest_summary = aliased(ModSummary)
        source_changed_at = func.coalesce(
            Mod.updated_at_remote,
            Mod.published_at_remote,
            Mod.created_at_remote,
            Mod.first_seen_at,
            "",
        )
        source_text = func.trim(func.coalesce(Mod.original_summary, Mod.title, ""))
        refresh_reasons = [
            latest_summary.id.is_(None),
            latest_summary.generated_at.is_(None),
            latest_summary.generated_at < source_changed_at,
        ]
        if _is_chinese_language(language) and self.session.get_bind().dialect.name == "sqlite":
            refresh_reasons.append(~latest_summary.content.op("GLOB")("*[一-鿿]*"))
            refresh_reasons.append(
                func.trim(func.coalesce(latest_summary.content, "")).like("{%")
                & latest_summary.content.like("%translated_summary%")
            )

        stmt = (
            select(Mod.id)
            .outerjoin(latest_summary_ids, latest_summary_ids.c.mod_id == Mod.id)
            .outerjoin(latest_summary, latest_summary.id == latest_summary_ids.c.latest_summary_id)
            .where(Mod.id.is_not(None), source_text != "", or_(*refresh_reasons))
            .order_by(source_changed_at.desc(), Mod.id.asc())
        )
        if mod_ids is not None:
            stmt = stmt.where(Mod.id.in_(mod_ids))
        if max_items is not None:
            stmt = stmt.limit(max_items)

        rows = self.session.exec(stmt).all()
        return [int(row) for row in rows if row is not None]
