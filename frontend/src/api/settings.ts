import { get, put, post, buildApiUrl, buildAuthHeaders, ApiError } from "./client";
import type { UserSettings, UILanguage, SummaryMode, LlmProvider, LlmProviderConfig, AccessProfile } from "@/types";

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

const DEFAULT_PROVIDER_BASE_URLS: Record<LlmProvider, string> = Object.fromEntries(
  DEFAULT_LLM_PROVIDERS.map((provider) => [provider.provider, provider.defaultBaseUrl]),
) as Record<LlmProvider, string>;

interface BackendSettings {
  nexus_api_key: string;
  google_search_api_key: string;
  google_search_engine_id: string;
  loverslab_search_scrape_enabled: string;
  loverslab_search_scrape_engine: string;
  llm_provider: string;
  llm_model: string;
  llm_api_key: string;
  llm_base_url: string;
  llm_providers_json: string;
  telegram_bot_token: string;
  telegram_chat_id: string;
  discord_webhook_url: string;
  telegram_enabled: string;
  discord_enabled: string;
  ui_language: string;
  summary_language: string;
  summary_mode: string;
  summary_report_interval_minutes: string;
  summary_report_prompt: string;
  watchdog_check_interval_minutes: string;
  watchdog_grace_minutes: string;
  watchdog_max_catchup_per_run: string;
  auto_start: string;
  notifications_enabled: string;
  system_notifications_enabled: string;
  database_path: string;
  proxy_enabled: string;
  proxy_type: string;
  proxy_host: string;
  proxy_port: string;
  proxy_username: string;
  proxy_password: string;
  access_profile: string;
  allow_lan: string;
  bind_host: string;
}

interface BackendLlmProviderConfig {
  provider: string;
  enabled: boolean;
  priority: number;
  model: string;
  api_key: string;
  base_url: string;
}

interface SettingsResponse {
  settings: BackendSettings;
}

function mapBackendToSettings(data: SettingsResponse): UserSettings {
  const s = data.settings;
  let llmProviders: LlmProviderConfig[] = [];
  try {
    const parsed = JSON.parse(s.llm_providers_json || "[]") as BackendLlmProviderConfig[];
    llmProviders = parsed.map((p) => ({
      provider: p.provider as LlmProvider,
      enabled: Boolean(p.enabled),
      priority: Number(p.priority) || 999,
      model: p.model || "",
      apiKey: p.api_key || "",
      baseUrl: p.base_url || DEFAULT_PROVIDER_BASE_URLS[p.provider as LlmProvider] || "",
    }));
  } catch {
    llmProviders = [];
  }
  if (llmProviders.length === 0) {
    llmProviders = [{
      provider: (s.llm_provider as LlmProvider) || "openai",
      enabled: true,
      priority: 1,
      model: s.llm_model || "",
      apiKey: s.llm_api_key || "",
      baseUrl: s.llm_base_url || DEFAULT_PROVIDER_BASE_URLS[(s.llm_provider as LlmProvider) || "openai"],
    }];
  }
  return {
    uiLanguage: (s.ui_language as UILanguage) || "zh-CN",
    summaryLanguage: (s.summary_language as UILanguage) || "zh-CN",
    summaryMode: (s.summary_mode as SummaryMode) || "bilingual",
    summaryReportIntervalMinutes: Number(s.summary_report_interval_minutes) || 0,
    summaryReportPrompt: s.summary_report_prompt || "",
    watchdogCheckIntervalMinutes: Number(s.watchdog_check_interval_minutes) || 10,
    watchdogGraceMinutes: Number(s.watchdog_grace_minutes) || 60,
    watchdogMaxCatchupPerRun: Number(s.watchdog_max_catchup_per_run) || 3,
    nexusApiKey: s.nexus_api_key || "",
    googleSearchApiKey: s.google_search_api_key || "",
    googleSearchEngineId: s.google_search_engine_id || "",
    loverslabSearchScrapeEnabled: s.loverslab_search_scrape_enabled !== "false",
    loverslabSearchScrapeEngine: (s.loverslab_search_scrape_engine as "duckduckgo" | "google") || "duckduckgo",
    llmProvider: (s.llm_provider as LlmProvider) || "openai",
    llmModel: s.llm_model || "",
    llmApiKey: s.llm_api_key || "",
    llmBaseUrl: s.llm_base_url || "",
    llmProviders,
    telegramEnabled: s.telegram_enabled === "true",
    telegramBotToken: s.telegram_bot_token || "",
    telegramChatId: s.telegram_chat_id || "",
    discordEnabled: s.discord_enabled === "true",
    discordWebhookUrl: s.discord_webhook_url || "",
    systemNotificationsEnabled: s.system_notifications_enabled !== "false",
    autoStart: s.auto_start === "true",
    notificationsEnabled: s.notifications_enabled !== "false",
    databasePath: s.database_path || "",
    proxyEnabled: s.proxy_enabled === "true",
    proxyType: (s.proxy_type as "http" | "socks5") || "http",
    proxyHost: s.proxy_host || "",
    proxyPort: s.proxy_port || "",
    proxyUsername: s.proxy_username || "",
    proxyPassword: s.proxy_password || "",
    accessProfile: (s.access_profile as AccessProfile) || "local_relaxed",
    allowLan: s.allow_lan === "true",
    bindHost: s.bind_host || "127.0.0.1",
  };
}

function mapSettingsToBackend(s: Partial<UserSettings>): { settings: Partial<BackendSettings> } {
  const settings: Partial<BackendSettings> = {};
  if (s.uiLanguage !== undefined) settings.ui_language = s.uiLanguage;
  if (s.summaryLanguage !== undefined) settings.summary_language = s.summaryLanguage;
  if (s.summaryMode !== undefined) settings.summary_mode = s.summaryMode;
  if (s.summaryReportIntervalMinutes !== undefined) settings.summary_report_interval_minutes = String(s.summaryReportIntervalMinutes);
  if (s.summaryReportPrompt !== undefined) settings.summary_report_prompt = s.summaryReportPrompt;
  if (s.watchdogCheckIntervalMinutes !== undefined) settings.watchdog_check_interval_minutes = String(s.watchdogCheckIntervalMinutes);
  if (s.watchdogGraceMinutes !== undefined) settings.watchdog_grace_minutes = String(s.watchdogGraceMinutes);
  if (s.watchdogMaxCatchupPerRun !== undefined) settings.watchdog_max_catchup_per_run = String(s.watchdogMaxCatchupPerRun);
  if (s.nexusApiKey !== undefined) settings.nexus_api_key = s.nexusApiKey;
  if (s.googleSearchApiKey !== undefined) settings.google_search_api_key = s.googleSearchApiKey;
  if (s.googleSearchEngineId !== undefined) settings.google_search_engine_id = s.googleSearchEngineId;
  if (s.loverslabSearchScrapeEnabled !== undefined) settings.loverslab_search_scrape_enabled = String(s.loverslabSearchScrapeEnabled);
  if (s.loverslabSearchScrapeEngine !== undefined) settings.loverslab_search_scrape_engine = s.loverslabSearchScrapeEngine;
  if (s.llmProvider !== undefined) settings.llm_provider = s.llmProvider;
  if (s.llmModel !== undefined) settings.llm_model = s.llmModel;
  if (s.llmApiKey !== undefined) settings.llm_api_key = s.llmApiKey;
  if (s.llmBaseUrl !== undefined) settings.llm_base_url = s.llmBaseUrl;
  if (s.llmProviders !== undefined) {
    settings.llm_providers_json = JSON.stringify(s.llmProviders.map((p) => ({
      provider: p.provider,
      enabled: p.enabled,
      priority: p.priority,
      model: p.model,
      api_key: p.apiKey,
      base_url: p.baseUrl,
    })));
    const primary = [...s.llmProviders].filter((p) => p.enabled).sort((a, b) => a.priority - b.priority)[0] ?? s.llmProviders[0];
    if (primary) {
      settings.llm_provider = primary.provider;
      settings.llm_model = primary.model;
      settings.llm_api_key = primary.apiKey;
      settings.llm_base_url = primary.baseUrl;
    }
  }
  if (s.telegramEnabled !== undefined) settings.telegram_enabled = String(s.telegramEnabled);
  if (s.telegramBotToken !== undefined) settings.telegram_bot_token = s.telegramBotToken;
  if (s.telegramChatId !== undefined) settings.telegram_chat_id = s.telegramChatId;
  if (s.discordEnabled !== undefined) settings.discord_enabled = String(s.discordEnabled);
  if (s.discordWebhookUrl !== undefined) settings.discord_webhook_url = s.discordWebhookUrl;
  if (s.systemNotificationsEnabled !== undefined) settings.system_notifications_enabled = String(s.systemNotificationsEnabled);
  if (s.autoStart !== undefined) settings.auto_start = String(s.autoStart);
  if (s.notificationsEnabled !== undefined) settings.notifications_enabled = String(s.notificationsEnabled);
  if (s.databasePath !== undefined) settings.database_path = s.databasePath;
  if (s.proxyEnabled !== undefined) settings.proxy_enabled = String(s.proxyEnabled);
  if (s.proxyType !== undefined) settings.proxy_type = s.proxyType;
  if (s.proxyHost !== undefined) settings.proxy_host = s.proxyHost;
  if (s.proxyPort !== undefined) settings.proxy_port = String(s.proxyPort);
  if (s.proxyUsername !== undefined) settings.proxy_username = s.proxyUsername;
  if (s.proxyPassword !== undefined) settings.proxy_password = s.proxyPassword;
  if (s.accessProfile !== undefined) settings.access_profile = s.accessProfile;
  if (s.allowLan !== undefined) settings.allow_lan = String(s.allowLan);
  if (s.bindHost !== undefined) settings.bind_host = s.bindHost;
  return { settings };
}

export async function fetchSettings(): Promise<UserSettings> {
  const data = await get<SettingsResponse>("/settings");
  return mapBackendToSettings(data);
}

export async function updateSettings(data: Partial<UserSettings>): Promise<UserSettings> {
  const body = mapSettingsToBackend(data);
  const result = await put<SettingsResponse>("/settings", body);
  return mapBackendToSettings(result);
}

export async function testTelegram(): Promise<{ success: boolean; message: string }> {
  return post<{ success: boolean; message: string }>("/settings/telegram/test");
}

export async function testDiscord(): Promise<{ success: boolean; message: string }> {
  return post<{ success: boolean; message: string }>("/settings/discord/test");
}

export interface LlmProviderTestResult {
  provider: string;
  success: boolean;
  latency_ms: number | null;
  message: string;
}

export async function testLlmProviders(providers: LlmProviderConfig[]): Promise<{ results: LlmProviderTestResult[] }> {
  return post<{ results: LlmProviderTestResult[] }>("/settings/llm/test", {
    providers: providers.map((p) => ({
      provider: p.provider,
      enabled: p.enabled,
      priority: p.priority,
      model: p.model,
      api_key: p.apiKey,
      base_url: p.baseUrl,
    })),
  });
}

export { DEFAULT_PROVIDER_BASE_URLS };

export async function exportSettings(): Promise<void> {
  const res = await fetch(buildApiUrl("/settings/export"), {
    method: "POST",
    headers: buildAuthHeaders(),
    credentials: "include",
  });
  if (!res.ok) {
    throw new ApiError(`API Error: ${res.status} ${res.statusText}`, res.status, "");
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = "mod_watcher_settings.json";
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

export async function importSettings(file: File): Promise<{ imported: number }> {
  const text = await file.text();
  const data = JSON.parse(text);
  const res = await fetch(buildApiUrl("/settings/import"), {
    method: "POST",
    headers: buildAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
    credentials: "include",
  });
  if (!res.ok) {
    throw new ApiError(`API Error: ${res.status} ${res.statusText}`, res.status, "");
  }
  return res.json();
}

export async function setAutoStart(enabled: boolean): Promise<{ success: boolean }> {
  return post<{ success: boolean }>("/settings/auto-start", { enabled });
}
