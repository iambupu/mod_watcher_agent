import type { LlmProvider } from "@/types";

export const DEFAULT_LLM_PROVIDERS: {
  provider: LlmProvider;
  label: string;
  defaultModel: string;
  defaultBaseUrl: string;
}[] = [
  { provider: "ollama", label: "Ollama (Local)", defaultModel: "qwen3:8b", defaultBaseUrl: "http://localhost:11434/v1" },
  { provider: "openai", label: "OpenAI", defaultModel: "gpt-4o-mini", defaultBaseUrl: "https://api.openai.com/v1" },
  { provider: "anthropic", label: "Anthropic", defaultModel: "claude-3-5-haiku-latest", defaultBaseUrl: "https://api.anthropic.com/v1" },
  { provider: "gemini", label: "Google Gemini", defaultModel: "gemini-2.0-flash", defaultBaseUrl: "https://generativelanguage.googleapis.com/v1" },
  { provider: "groq", label: "Groq", defaultModel: "mixtral-8x7b-32768", defaultBaseUrl: "https://api.groq.com/openai/v1" },
  { provider: "deepseek", label: "DeepSeek", defaultModel: "deepseek-v4-flash", defaultBaseUrl: "https://api.deepseek.com/v1" },
  { provider: "openrouter", label: "OpenRouter", defaultModel: "gpt-4o-mini", defaultBaseUrl: "https://openrouter.ai/api/v1" },
  { provider: "siliconflow", label: "硅基流动 (SiliconFlow)", defaultModel: "Qwen/Qwen3-8B", defaultBaseUrl: "https://api.siliconflow.cn/v1" },
  { provider: "xai", label: "xAI", defaultModel: "grok-4.20-reasoning", defaultBaseUrl: "https://api.x.ai/v1" },
  { provider: "kimi", label: "Kimi", defaultModel: "kimi-k2.6", defaultBaseUrl: "https://api.moonshot.cn/v1" },
  { provider: "qwen", label: "通义千问 (Qwen)", defaultModel: "qwen-plus", defaultBaseUrl: "https://dashscope.aliyuncs.com/compatible-mode/v1" },
  { provider: "minimax", label: "MiniMax", defaultModel: "MiniMax-M2.7", defaultBaseUrl: "https://api.minimax.io/v1" },
];

export const DEFAULT_PROVIDER_BASE_URLS: Record<LlmProvider, string> = Object.fromEntries(
  DEFAULT_LLM_PROVIDERS.map((provider) => [provider.provider, provider.defaultBaseUrl]),
) as Record<LlmProvider, string>;

export const KNOWN_LLM_PROVIDERS = new Set<LlmProvider>(
  DEFAULT_LLM_PROVIDERS.map((provider) => provider.provider),
);
