import { get, put, post, buildApiUrl, buildAuthHeaders, apiErrorFromResponse } from "./client";
import {
  ACCESS_PROFILES,
  LOVERSLAB_SEARCH_SCRAPE_ENGINES,
  PROXY_TYPES,
  SETTINGS_NUMERIC_BOUNDS,
  SUMMARY_MODES,
  UI_LANGUAGES,
} from "@/constants/settings";
import { DEFAULT_PROVIDER_BASE_URLS, KNOWN_LLM_PROVIDERS } from "@/constants/llmProviders";
import type { UserSettings, UILanguage, SummaryMode, LlmProvider, LlmProviderConfig, AccessProfile } from "@/types";
import { parseBoolean } from "@/utils/boolean";
import { parseJsonArray, parseJsonText } from "@/utils/json";
import { clampIntegerInput } from "@/utils/numberInput";

const KNOWN_UI_LANGUAGES = new Set<UILanguage>(UI_LANGUAGES);
const KNOWN_SUMMARY_MODES = new Set<SummaryMode>(SUMMARY_MODES);
const KNOWN_LOVERSLAB_SEARCH_SCRAPE_ENGINES = new Set<UserSettings["loverslabSearchScrapeEngine"]>(
  LOVERSLAB_SEARCH_SCRAPE_ENGINES,
);
const KNOWN_PROXY_TYPES = new Set<UserSettings["proxyType"]>(PROXY_TYPES);
const KNOWN_ACCESS_PROFILES = new Set<AccessProfile>(ACCESS_PROFILES);

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
  llmProviders = parseJsonArray(s.llm_providers_json).flatMap((item) => {
    if (!item || typeof item !== "object" || Array.isArray(item)) return [];
    const p = item as Partial<BackendLlmProviderConfig>;
    const provider = p.provider || "";
    if (!isKnownLlmProvider(provider)) return [];
    return [{
      provider,
      enabled: parseBoolean(p.enabled),
      priority: clampIntegerInput(String(p.priority ?? ""), { min: 1, max: 999, fallback: 999 }),
      model: p.model || "",
      apiKey: p.api_key || "",
      baseUrl: p.base_url || DEFAULT_PROVIDER_BASE_URLS[provider] || "",
    }];
  });
  const primaryProvider = isKnownLlmProvider(s.llm_provider) ? s.llm_provider : "openai";
  if (llmProviders.length === 0) {
    llmProviders = [{
      provider: primaryProvider,
      enabled: true,
      priority: 1,
      model: s.llm_model || "",
      apiKey: s.llm_api_key || "",
      baseUrl: s.llm_base_url || DEFAULT_PROVIDER_BASE_URLS[primaryProvider],
    }];
  }
  return {
    uiLanguage: knownValue(KNOWN_UI_LANGUAGES, s.ui_language, "zh-CN"),
    summaryLanguage: knownValue(KNOWN_UI_LANGUAGES, s.summary_language, "zh-CN"),
    summaryMode: knownValue(KNOWN_SUMMARY_MODES, s.summary_mode, "bilingual"),
    summaryReportIntervalMinutes: clampIntegerInput(
      s.summary_report_interval_minutes ?? "",
      SETTINGS_NUMERIC_BOUNDS.summaryReportIntervalMinutes,
    ),
    summaryReportPrompt: s.summary_report_prompt || "",
    watchdogCheckIntervalMinutes: clampIntegerInput(
      s.watchdog_check_interval_minutes ?? "",
      SETTINGS_NUMERIC_BOUNDS.watchdogCheckIntervalMinutes,
    ),
    watchdogGraceMinutes: clampIntegerInput(
      s.watchdog_grace_minutes ?? "",
      SETTINGS_NUMERIC_BOUNDS.watchdogGraceMinutes,
    ),
    watchdogMaxCatchupPerRun: clampIntegerInput(
      s.watchdog_max_catchup_per_run ?? "",
      SETTINGS_NUMERIC_BOUNDS.watchdogMaxCatchupPerRun,
    ),
    nexusApiKey: s.nexus_api_key || "",
    googleSearchApiKey: s.google_search_api_key || "",
    googleSearchEngineId: s.google_search_engine_id || "",
    loverslabSearchScrapeEnabled: parseBoolean(s.loverslab_search_scrape_enabled, true),
    loverslabSearchScrapeEngine: knownValue(
      KNOWN_LOVERSLAB_SEARCH_SCRAPE_ENGINES,
      s.loverslab_search_scrape_engine,
      "duckduckgo",
    ),
    llmProvider: primaryProvider,
    llmModel: s.llm_model || "",
    llmApiKey: s.llm_api_key || "",
    llmBaseUrl: s.llm_base_url || "",
    llmProviders,
    telegramEnabled: parseBoolean(s.telegram_enabled),
    telegramBotToken: s.telegram_bot_token || "",
    telegramChatId: s.telegram_chat_id || "",
    discordEnabled: parseBoolean(s.discord_enabled),
    discordWebhookUrl: s.discord_webhook_url || "",
    systemNotificationsEnabled: parseBoolean(s.system_notifications_enabled, true),
    autoStart: parseBoolean(s.auto_start),
    notificationsEnabled: parseBoolean(s.notifications_enabled, true),
    databasePath: s.database_path || "",
    proxyEnabled: parseBoolean(s.proxy_enabled),
    proxyType: knownValue(KNOWN_PROXY_TYPES, s.proxy_type, "http"),
    proxyHost: s.proxy_host || "",
    proxyPort: s.proxy_port || "",
    proxyUsername: s.proxy_username || "",
    proxyPassword: s.proxy_password || "",
    accessProfile: knownValue(KNOWN_ACCESS_PROFILES, s.access_profile, "local_relaxed"),
    allowLan: parseBoolean(s.allow_lan),
    bindHost: s.bind_host || "127.0.0.1",
  };
}

function isKnownLlmProvider(provider: string): provider is LlmProvider {
  return KNOWN_LLM_PROVIDERS.has(provider as LlmProvider);
}

function knownValue<T extends string>(knownValues: Set<T>, raw: string | undefined, fallback: T): T {
  return knownValues.has(raw as T) ? (raw as T) : fallback;
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

export async function exportSettings(): Promise<void> {
  const res = await fetch(buildApiUrl("/settings/export"), {
    method: "POST",
    headers: buildAuthHeaders(),
    credentials: "include",
  });
  if (!res.ok) {
    throw await apiErrorFromResponse(res);
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
  const data = parseJsonText(text);
  if (!data || typeof data !== "object" || Array.isArray(data)) {
    throw new Error("Settings import file must be a JSON object");
  }
  const res = await fetch(buildApiUrl("/settings/import"), {
    method: "POST",
    headers: buildAuthHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(data),
    credentials: "include",
  });
  if (!res.ok) {
    throw await apiErrorFromResponse(res);
  }
  return res.json();
}

export async function setAutoStart(enabled: boolean): Promise<{ success: boolean }> {
  return post<{ success: boolean }>("/settings/auto-start", { enabled });
}
