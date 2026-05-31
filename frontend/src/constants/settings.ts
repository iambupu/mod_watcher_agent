import type { AccessProfile, SummaryMode, UILanguage } from "@/types";

export const SETTINGS_NUMERIC_BOUNDS = {
  summaryReportIntervalMinutes: { min: 0, max: 10080, fallback: 0 },
  watchdogCheckIntervalMinutes: { min: 1, max: 180, fallback: 10 },
  watchdogGraceMinutes: { min: 1, max: 1440, fallback: 60 },
  watchdogMaxCatchupPerRun: { min: 1, max: 20, fallback: 3 },
} as const;

export const UI_LANGUAGES = ["zh-CN", "en-US", "ja-JP"] as const satisfies readonly UILanguage[];
export const SUMMARY_MODES = ["original", "translated", "bilingual"] as const satisfies readonly SummaryMode[];
export const LOVERSLAB_SEARCH_SCRAPE_ENGINES = ["duckduckgo", "google"] as const;
export const PROXY_TYPES = ["http", "socks5"] as const;
export const ACCESS_PROFILES = ["local_relaxed", "local_strict", "shared_lan"] as const satisfies readonly AccessProfile[];
