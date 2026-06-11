import json
import logging
from abc import ABC, abstractmethod

import httpx
from sqlmodel import Session as _Session

from app.schemas.watch_rule import LlmFilterConfig
from app.security import validate_outbound_url
from app.services.llm_provider_config import DEFAULT_MODELS as DEFAULT_MODELS
from app.services.llm_provider_config import (
    SUPPORTED_PROVIDERS,
    get_provider_chain,
    provider_config_has_credentials,
    resolve_provider_config,
)
from app.services.settings_service import SettingsService
from app.utils.json import json_array_from_text

logger = logging.getLogger(__name__)

class LLMClient(ABC):
    last_error: str = ""
    last_detail: str = ""

    @abstractmethod
    async def chat(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        request_timeout: float | None = None,
    ) -> str:
        """发送聊天请求并返回模型文本内容。"""
        ...


class OpenAIClient(LLMClient):
    """OpenAI-compatible API: OpenAI, Groq, DeepSeek, OpenRouter, Ollama, SiliconFlow, xAI, Kimi, Qwen, MiniMax"""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        """保存 OpenAI 兼容接口凭据和 base_url。"""
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def chat(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        request_timeout: float | None = None,
    ) -> str:
        """调用 OpenAI 兼容 chat/completions 接口。"""
        self.last_error = ""
        self.last_detail = ""
        try:
            endpoint = f"{self.base_url}/chat/completions"
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": max_tokens,
                "stream": False,
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=request_timeout or 60.0,
                )
                response.raise_for_status()
                data = response.json()

            choice = _first_dict(data.get("choices"))
            message = choice.get("message") if choice else {}
            message = message if isinstance(message, dict) else {}
            content = str(message.get("content") or "").strip()
            if not content:
                finish_reason = choice.get("finish_reason") or "unknown"
                reasoning = message.get("reasoning") or message.get("reasoning_content")
                if reasoning:
                    self.last_detail = (
                        f"HTTP OK but content was empty; finish_reason={finish_reason}; "
                        "model returned reasoning text before final content."
                    )
                else:
                    self.last_detail = f"HTTP OK but content was empty; finish_reason={finish_reason}."
            return content
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("OpenAI-compatible LLM request failed: %s", exc)
            return ""


class AnthropicClient(LLMClient):
    """Native Anthropic API format"""

    DEFAULT_BASE_URL = "https://api.anthropic.com/v1"

    def __init__(self, api_key: str):
        """保存 Anthropic API key。"""
        self.api_key = api_key

    async def chat(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        request_timeout: float | None = None,
    ) -> str:
        """调用 Anthropic messages 接口并提取首个文本块。"""
        self.last_error = ""
        self.last_detail = ""
        try:
            endpoint = f"{self.DEFAULT_BASE_URL}/messages"
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            }
            body = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    headers=headers,
                    json=body,
                    timeout=request_timeout or 60.0,
                )
                response.raise_for_status()
                data = response.json()

            content = _anthropic_content_text(data).strip()
            if not content:
                self.last_detail = "HTTP OK but content was empty."
            return content
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Anthropic LLM request failed: %s", exc)
            return ""


class GeminiClient(LLMClient):
    """Native Google Gemini API format"""

    def __init__(self, api_key: str):
        """保存 Gemini API key。"""
        self.api_key = api_key

    async def chat(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        request_timeout: float | None = None,
    ) -> str:
        """调用 Gemini generateContent 接口并提取首个候选文本。"""
        self.last_error = ""
        self.last_detail = ""
        try:
            endpoint = (
                "https://generativelanguage.googleapis.com/v1/models/"
                f"{model}:generateContent?key={self.api_key}"
            )
            body = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            }

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    json=body,
                    timeout=request_timeout or 60.0,
                )
                response.raise_for_status()
                data = response.json()

            content = _gemini_content_text(data).strip()
            if not content:
                self.last_detail = "HTTP OK but content was empty."
            return content
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Gemini LLM request failed: %s", exc)
            return ""


class OllamaClient(LLMClient):
    """Native Ollama API client. Uses think=false so reasoning models return final content."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        """保存 Ollama 地址，并把 OpenAI 兼容 /v1 地址还原为原生地址。"""
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.base_url = base
        self.last_error = ""
        self.last_detail = ""

    async def chat(
        self,
        prompt: str,
        model: str,
        max_tokens: int = 1024,
        request_timeout: float | None = None,
    ) -> str:
        """调用 Ollama 原生 chat 接口并关闭思考输出。"""
        self.last_error = ""
        self.last_detail = ""
        try:
            endpoint = f"{self.base_url}/api/chat"
            body = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "think": False,
                "options": {"num_predict": max_tokens},
            }
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    endpoint,
                    json=body,
                    timeout=request_timeout or 60.0,
                )
                response.raise_for_status()
                data = response.json()
            message = data.get("message") or {}
            content = str(message.get("content") or "").strip()
            if not content:
                self.last_detail = (
                    f"HTTP OK but content was empty; done_reason={data.get('done_reason') or 'unknown'}."
                )
            return content
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Ollama LLM request failed: %s", exc)
            return ""


def _first_dict(value: object) -> dict:
    if not isinstance(value, list) or not value:
        return {}
    first = value[0]
    return first if isinstance(first, dict) else {}


def _anthropic_content_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    block = _first_dict(data.get("content"))
    return str(block.get("text") or "")


def _gemini_content_text(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    candidate = _first_dict(data.get("candidates"))
    content = candidate.get("content") if isinstance(candidate, dict) else {}
    content = content if isinstance(content, dict) else {}
    part = _first_dict(content.get("parts"))
    return str(part.get("text") or "")


def create_llm_client(
    provider: str,
    api_key: str = "",
    base_url: str = "",
) -> LLMClient:
    """根据 provider 名称创建对应的 LLM 客户端。"""
    provider = provider.lower().strip()
    base_url = validate_outbound_url(provider, base_url)

    if provider == "ollama":
        return OllamaClient(base_url)

    if provider in ("openai", "groq", "deepseek", "openrouter", "siliconflow", "xai", "kimi", "qwen", "minimax"):
        return OpenAIClient(api_key, base_url)

    if provider == "anthropic":
        return AnthropicClient(api_key)

    if provider == "gemini":
        return GeminiClient(api_key)

    raise ValueError(
        f"Unsupported LLM provider: {provider!r}. Supported: {', '.join(sorted(SUPPORTED_PROVIDERS))}"
    )


# ---------------------------------------------------------------------------
#  LLM-assisted rule filter (synchronous, used by FilterService)
# ---------------------------------------------------------------------------

_MAX_MODS_PER_LLM_CALL = 50
_REQUEST_TIMEOUT = 30.0


def create_llm_filter_client(session: _Session):
    """Return a synchronous LLM filter callable, or None if not configured.

    Reads llm_providers_json from DB settings, picks the first enabled
    provider with an API key, and returns ``fn(mods, llm_config)``.
    """

    svc = SettingsService(session)
    primary = next(
        (provider for provider in get_provider_chain(svc) if provider_config_has_credentials(provider)),
        None,
    )
    if primary is None:
        return None
    primary_provider, primary_api_key, primary_base_url_raw, primary_model = resolve_provider_config(primary)
    primary_base_url = validate_outbound_url(primary_provider, primary_base_url_raw)

    def _llm_filter(
        mods: list[dict],
        llm_config: LlmFilterConfig,
        return_details: bool = False,
    ) -> list[dict] | dict:
        """同步调用 LLM 对候选 Mod 批量返回保留索引。"""
        if not mods:
            return {"items": [], "details": []} if return_details else []
        system_prompt = (
            "You are a mod filter. Given a list of mods (index, title, summary), "
            "return ONLY a JSON array of the indices that SHOULD BE KEPT "
            "(i.e. that match the filter criteria). "
            "Do not include any other text."
        )

        kept: list[dict] = []
        details: list[dict] = []
        for start in range(0, len(mods), _MAX_MODS_PER_LLM_CALL):
            batch = mods[start:start + _MAX_MODS_PER_LLM_CALL]

            mod_list = []
            for i, m in enumerate(batch):
                mod_list.append({
                    "index": i,
                    "title": (m.get("title") or "")[:300],
                    "summary": (m.get("original_summary") or "")[:500],
                })

            user_prompt = (
                f"Filter criteria:\n{llm_config.prompt}\n\n"
                f"Mods to evaluate:\n{json.dumps(mod_list, ensure_ascii=False)}"
            )

            try:
                resp = httpx.post(
                    f"{primary_base_url.rstrip('/')}/chat/completions",
                    json={
                        "model": primary_model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        "temperature": 0.1,
                    },
                    headers={
                        "Authorization": f"Bearer {primary_api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=_REQUEST_TIMEOUT,
                )
                resp.raise_for_status()
                data = resp.json()

                choice = _first_dict(data.get("choices")) if isinstance(data, dict) else {}
                message = choice.get("message") if isinstance(choice.get("message"), dict) else {}
                content = str(message.get("content") or "")
                raw_indices = json_array_from_text(content)
                if raw_indices is None:
                    logger.warning("LLM response had no index array: %s", content[:200])
                    if llm_config.mode == "assist_only":
                        kept.extend(batch)
                        if return_details:
                            for mod in batch:
                                details.append(
                                    {
                                        "mod": mod,
                                        "decision": "keep",
                                        "feedback": "llm_no_index_array_assist_only_fallback",
                                    }
                                )
                    elif return_details:
                        for mod in batch:
                            details.append(
                                {
                                    "mod": mod,
                                    "decision": "reject",
                                    "feedback": "llm_no_index_array_rejected_in_must_pass",
                                }
                    )
                    continue

                indices = _valid_filter_indices(raw_indices, batch_size=len(batch))
                kept_idx = set(indices)
                if return_details:
                    for i, mod in enumerate(batch):
                        details.append(
                            {
                                "mod": mod,
                                "decision": "keep" if i in kept_idx else "reject",
                                "feedback": content[:500],
                            }
                        )
                kept.extend([batch[i] for i in indices])

            except Exception:
                logger.exception("LLM filter call failed for provider %s", primary.get("provider"))
                if llm_config.mode == "assist_only":
                    kept.extend(batch)
                    if return_details:
                        for mod in batch:
                            details.append(
                                {
                                    "mod": mod,
                                    "decision": "keep",
                                    "feedback": "llm_error_assist_only_fallback",
                                }
                            )
                elif return_details:
                    for mod in batch:
                        details.append(
                            {
                                "mod": mod,
                                "decision": "reject",
                                "feedback": "llm_error_rejected_in_must_pass",
                            }
                        )

        if return_details:
            return {"items": kept, "details": details}
        return kept

    return _llm_filter


def _valid_filter_indices(raw: str | list, *, batch_size: int) -> list[int]:
    parsed = raw if isinstance(raw, list) else json_array_from_text(raw)
    if not isinstance(parsed, list):
        return []
    seen: set[int] = set()
    indices: list[int] = []
    for item in parsed:
        if not isinstance(item, int) or isinstance(item, bool):
            continue
        if item < 0 or item >= batch_size or item in seen:
            continue
        indices.append(item)
        seen.add(item)
    return indices
