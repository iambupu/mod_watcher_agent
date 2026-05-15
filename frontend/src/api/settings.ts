import { get, put, post } from "./client";
import type { UserSettings, UILanguage, SummaryMode, LlmProvider, LlmProviderConfig } from "@/types";

const DEFAULT_PROVIDER_BASE_URLS: Record<LlmProvider, string> = {
  openai: "https://api.openai.com/v1",
  anthropic: "https://api.anthropic.com/v1",
  gemini: "https://generativelanguage.googleapis.com/v1",
  groq: "https://api.groq.com/openai/v1",
  deepseek: "https://api.deepseek.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  ollama: "http://localhost:11434/v1",
};

interface BackendSettings {
  nexus_api_key: string;
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
    nexusApiKey: s.nexus_api_key || "",
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
  };
}

function mapSettingsToBackend(s: Partial<UserSettings>): { settings: Partial<BackendSettings> } {
  const settings: Partial<BackendSettings> = {};
  if (s.uiLanguage !== undefined) settings.ui_language = s.uiLanguage;
  if (s.summaryLanguage !== undefined) settings.summary_language = s.summaryLanguage;
  if (s.summaryMode !== undefined) settings.summary_mode = s.summaryMode;
  if (s.summaryReportIntervalMinutes !== undefined) settings.summary_report_interval_minutes = String(s.summaryReportIntervalMinutes);
  if (s.summaryReportPrompt !== undefined) settings.summary_report_prompt = s.summaryReportPrompt;
  if (s.nexusApiKey !== undefined) settings.nexus_api_key = s.nexusApiKey;
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
  return { settings };
}

export async function fetchSettings(): Promise<UserSettings> {
  const data = await get<SettingsResponse>("/settings");
  return mapBackendToSettings(data);
}

export const getSettings = fetchSettings;

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
  const res = await fetch("/api/settings/export", { method: "POST" });
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
  const res = await fetch("/api/settings/import", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
  return res.json();
}

export async function setAutoStart(enabled: boolean): Promise<{ success: boolean }> {
  return post<{ success: boolean }>("/settings/auto-start", { enabled });
}
