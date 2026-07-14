// 中文注释：封装前端访问后端设置接口的类型和请求函数。

import { get, put, post, buildApiUrl, buildAuthHeaders, apiErrorFromResponse } from "./client";
import {
  ACCESS_PROFILES,
  LOVERSLAB_SEARCH_SCRAPE_ENGINES,
  PROXY_TYPES,
  SETTINGS_NUMERIC_BOUNDS,
  SUMMARY_MODES,
  UI_LANGUAGES,
} from "@/constants/settings";
import type { UserSettings, UILanguage, SummaryMode, LlmProviderConfig, AccessProfile } from "@/types";
import { parseBoolean } from "@/utils/boolean";
import { parseJsonText } from "@/utils/json";
import { clampIntegerInput } from "@/utils/numberInput";
import {
  isKnownLlmProvider,
  parseLlmProviders,
  serializeLlmProviders,
} from "./llmProviderCodec";

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

interface SettingsResponse {
  settings: BackendSettings;
}

interface BackendRuntimePaths {
  config_dir: string;
  default_database_path: string;
  active_database_path: string;
}

export interface RuntimePathsInfo {
  configDir: string;
  defaultDatabasePath: string;
  activeDatabasePath: string;
}

function mapBackendToSettings(data: SettingsResponse): UserSettings {
  const s = data.settings;
  const primaryProvider = isKnownLlmProvider(s.llm_provider) ? s.llm_provider : "openai";
  const llmProviders = parseLlmProviders(s.llm_providers_json, {
    provider: s.llm_provider,
    model: s.llm_model || "",
    apiKey: s.llm_api_key || "",
    baseUrl: s.llm_base_url || "",
  });
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

function knownValue<T extends string>(knownValues: Set<T>, raw: string | undefined, fallback: T): T {
  return knownValues.has(raw as T) ? (raw as T) : fallback;
}

function mapSettingsToBackend(s: Partial<UserSettings>): { settings: Partial<BackendSettings> } {
  const settings: Partial<BackendSettings> = {};
  const assign = (key: keyof BackendSettings, value: unknown) => {
    if (value !== undefined) (settings as Record<string, string>)[key] = String(value);
  };

  assign("ui_language", s.uiLanguage);
  assign("summary_language", s.summaryLanguage);
  assign("summary_mode", s.summaryMode);
  assign("summary_report_interval_minutes", s.summaryReportIntervalMinutes);
  assign("summary_report_prompt", s.summaryReportPrompt);
  assign("watchdog_check_interval_minutes", s.watchdogCheckIntervalMinutes);
  assign("watchdog_grace_minutes", s.watchdogGraceMinutes);
  assign("watchdog_max_catchup_per_run", s.watchdogMaxCatchupPerRun);
  assign("nexus_api_key", s.nexusApiKey);
  assign("google_search_api_key", s.googleSearchApiKey);
  assign("google_search_engine_id", s.googleSearchEngineId);
  assign("loverslab_search_scrape_enabled", s.loverslabSearchScrapeEnabled);
  assign("loverslab_search_scrape_engine", s.loverslabSearchScrapeEngine);
  assign("llm_provider", s.llmProvider);
  assign("llm_model", s.llmModel);
  assign("llm_api_key", s.llmApiKey);
  assign("llm_base_url", s.llmBaseUrl);
  if (s.llmProviders !== undefined) {
    settings.llm_providers_json = JSON.stringify(serializeLlmProviders(s.llmProviders));
    const primary = [...s.llmProviders].filter((p) => p.enabled).sort((a, b) => a.priority - b.priority)[0] ?? s.llmProviders[0];
    if (primary) {
      settings.llm_provider = primary.provider;
      settings.llm_model = primary.model;
      settings.llm_api_key = primary.apiKey;
      settings.llm_base_url = primary.baseUrl;
    }
  }
  assign("telegram_enabled", s.telegramEnabled);
  assign("telegram_bot_token", s.telegramBotToken);
  assign("telegram_chat_id", s.telegramChatId);
  assign("discord_enabled", s.discordEnabled);
  assign("discord_webhook_url", s.discordWebhookUrl);
  assign("system_notifications_enabled", s.systemNotificationsEnabled);
  assign("auto_start", s.autoStart);
  assign("notifications_enabled", s.notificationsEnabled);
  assign("database_path", s.databasePath);
  assign("proxy_enabled", s.proxyEnabled);
  assign("proxy_type", s.proxyType);
  assign("proxy_host", s.proxyHost);
  assign("proxy_port", s.proxyPort);
  assign("proxy_username", s.proxyUsername);
  assign("proxy_password", s.proxyPassword);
  assign("access_profile", s.accessProfile);
  assign("allow_lan", s.allowLan);
  assign("bind_host", s.bindHost);
  return { settings };
}

export async function fetchSettings(): Promise<UserSettings> {
  const data = await get<SettingsResponse>("/settings");
  return mapBackendToSettings(data);
}

export async function fetchRuntimePaths(): Promise<RuntimePathsInfo> {
  const paths = await get<BackendRuntimePaths>("/settings/runtime-paths");
  return {
    configDir: paths.config_dir,
    defaultDatabasePath: paths.default_database_path,
    activeDatabasePath: paths.active_database_path,
  };
}

export function openConfigDirectory(): Promise<{ opened: boolean; path: string }> {
  return post<{ opened: boolean; path: string }>("/settings/open-config-dir");
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
    providers: serializeLlmProviders(providers),
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
