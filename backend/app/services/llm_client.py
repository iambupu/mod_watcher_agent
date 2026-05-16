from abc import ABC, abstractmethod
import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-3-5-haiku-latest",
    "gemini": "gemini-2.0-flash",
    "groq": "mixtral-8x7b-32768",
    "deepseek": "deepseek-chat",
    "openrouter": "gpt-4o-mini",
    "ollama": "llama3.2",
}


class LLMClient(ABC):
    last_error: str = ""
    last_detail: str = ""

    @abstractmethod
    async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
        ...


class OpenAIClient(LLMClient):
    """OpenAI-compatible API: OpenAI, Groq, DeepSeek, OpenRouter, Ollama"""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")

    async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
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
                    endpoint, headers=headers, json=body, timeout=60.0
                )
                response.raise_for_status()
                data = response.json()

            choice = data["choices"][0]
            message = choice.get("message") or {}
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
        self.api_key = api_key

    async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
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
                    endpoint, headers=headers, json=body, timeout=60.0
                )
                response.raise_for_status()
                data = response.json()

            return data["content"][0]["text"].strip()
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Anthropic LLM request failed: %s", exc)
            return ""


class GeminiClient(LLMClient):
    """Native Google Gemini API format"""

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
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
                    endpoint, json=body, timeout=60.0
                )
                response.raise_for_status()
                data = response.json()

            return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("Gemini LLM request failed: %s", exc)
            return ""


class OllamaClient(LLMClient):
    """Native Ollama API client. Uses think=false so reasoning models return final content."""

    def __init__(self, base_url: str = "http://localhost:11434"):
        base = base_url.rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.base_url = base
        self.last_error = ""
        self.last_detail = ""

    async def chat(self, prompt: str, model: str, max_tokens: int = 1024) -> str:
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
                response = await client.post(endpoint, json=body, timeout=60.0)
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


def create_llm_client(
    provider: str,
    api_key: str = "",
    base_url: str = "",
) -> LLMClient:
    provider = provider.lower().strip()

    if provider == "ollama":
        return OllamaClient(base_url or "http://localhost:11434")

    if provider in ("openai", "groq", "deepseek", "openrouter"):
        if not base_url:
            base_url = {
                "groq": "https://api.groq.com/openai/v1",
                "deepseek": "https://api.deepseek.com/v1",
                "openrouter": "https://openrouter.ai/api/v1",
            }.get(provider, "https://api.openai.com/v1")
        return OpenAIClient(api_key, base_url)

    if provider == "anthropic":
        return AnthropicClient(api_key)

    if provider == "gemini":
        return GeminiClient(api_key)

    supported = {"openai", "groq", "deepseek", "openrouter", "anthropic", "gemini", "ollama"}
    raise ValueError(
        f"Unsupported LLM provider: {provider!r}. Supported: {', '.join(sorted(supported))}"
    )
