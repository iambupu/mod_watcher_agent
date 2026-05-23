export type ModSource = "nexusmods" | "loverslab";
export type AdultPolicy = "include" | "exclude" | "only";
export type SummaryMode = "original" | "translated" | "bilingual";
export type UILanguage = "zh-CN" | "en-US" | "ja-JP";
export type LlmProvider =
  | "openai"
  | "anthropic"
  | "gemini"
  | "groq"
  | "deepseek"
  | "openrouter"
  | "ollama"
  | "siliconflow"
  | "xai"
  | "kimi"
  | "qwen"
  | "minimax";
export type AccessProfile = "local_relaxed" | "local_strict" | "shared_lan";

export interface LlmProviderConfig {
  provider: LlmProvider;
  enabled: boolean;
  priority: number;
  model: string;
  apiKey: string;
  baseUrl: string;
}

export interface ModItem {
  id: number;
  source: ModSource;
  external_id: string;
  game: string;
  game_domain?: string;
  title: string;
  url: string;
  author?: string;
  category?: string;
  tags_json: string;
  original_summary?: string;
  translated_summary?: string;
  ai_introduction?: string;
  version?: string;
  created_at_remote?: string;
  updated_at_remote?: string;
  published_at_remote?: string;
  downloads?: number;
  unique_downloads?: number;
  endorsements?: number;
  views?: number;
  likes?: number;
  adult_content?: boolean;
  thumbnail_url?: string;
  ignored: boolean;
  first_seen_at: string;
  last_seen_at: string;
}

export interface ModList {
  items: ModItem[];
  total: number;
}

export interface Favorite {
  id: number;
  modId: number;
  mod: ModItem;
  trackingEnabled: boolean;
  notifyOnUpdate: boolean;
  userNote?: string;
  userTags: string[];
  lastKnownVersion?: string;
  lastKnownUpdatedAt?: string;
  lastCheckedAt?: string;
}

export interface UpdateEvent {
  id: number;
  modId: number;
  mod: ModItem;
  oldVersion?: string;
  newVersion?: string;
  oldUpdatedAt?: string;
  newUpdatedAt?: string;
  rawChangelog?: string;
  changeSummary?: string;
  detectedAt: string;
  seen: boolean;
}

export interface UserSettings {
  uiLanguage: UILanguage;
  summaryLanguage: UILanguage;
  summaryMode: SummaryMode;
  summaryReportIntervalMinutes: number;
  summaryReportPrompt: string;
  watchdogCheckIntervalMinutes: number;
  watchdogGraceMinutes: number;
  watchdogMaxCatchupPerRun: number;
  // Credentials
  nexusApiKey: string;
  googleSearchApiKey: string;
  googleSearchEngineId: string;
  loverslabSearchScrapeEnabled: boolean;
  loverslabSearchScrapeEngine: "duckduckgo" | "google";
  // LLM
  llmProvider: LlmProvider;
  llmModel: string;
  llmApiKey: string;
  llmBaseUrl: string;
  llmProviders: LlmProviderConfig[];
  // Notification
  telegramEnabled: boolean;
  telegramBotToken: string;
  telegramChatId: string;
  discordEnabled: boolean;
  discordWebhookUrl: string;
  systemNotificationsEnabled: boolean;
  autoStart: boolean;
  notificationsEnabled: boolean;
  databasePath: string;
  proxyEnabled: boolean;
  proxyType: "http" | "socks5";
  proxyHost: string;
  proxyPort: string;
  proxyUsername: string;
  proxyPassword: string;
  accessProfile: AccessProfile;
  allowLan: boolean;
  bindHost: string;
}

// ── Rule Types ───────────────────────────────────────────────

export type RuleSource = ModSource;
export type LlmFilterMode = "assist_only" | "must_pass";
export type NotifyMode = "instant" | "daily_digest" | "weekly_digest";
export type MissingMetricsPolicy = "pass" | "reject";
type AccessMode = "rss" | "page" | "both";

export interface NexusModsRuleConfig {
  gameDomainName: string;
  updatedSinceDays: number;
  queryMode?: "updated" | "created";
  sortBy?: "updatedAt_desc" | "createdAt_desc" | "downloads_desc" | "endorsements_desc";
  categoryNames?: string[];
  tags?: string[];
}

export interface LoversLabRuleConfig {
  gameLabel: string;
  accessMode?: AccessMode;
  feedUrls?: string[];
  pageUrls?: string[];
  browserProfile?: string;
  updatedSinceDays?: number;
  maxItemsPerRun?: number;
  updateDetection?: "published_time" | "updated_time" | "page_hash";
}

export interface LlmFilterConfig {
  enabled: boolean;
  prompt?: string;
  mode: LlmFilterMode;
  minConfidence?: number;
}

export interface CommonRuleFilters {
  includeKeywords?: string[];
  excludeKeywords?: string[];
  minDownloads?: number;
  minEndorsements?: number;
  minLikes?: number;
  updatedWithinDays?: number;
  adultPolicy?: AdultPolicy;
  missingMetricsPolicy?: MissingMetricsPolicy;
  llmFilter?: LlmFilterConfig;
}

export interface NotificationConfig {
  enabled: boolean;
  mode: NotifyMode;
  channels?: string[];
}

export interface WatchRule {
  id: number;
  name: string;
  enabled: boolean;
  intervalMinutes: number;
  source: ModSource;
  sourceConfig: NexusModsRuleConfig | LoversLabRuleConfig;
  filters: CommonRuleFilters;
  notification: NotificationConfig;
  createdAt: string;
  updatedAt: string;
}

export interface RuleTestRequest {
  rule: WatchRuleCreate;
  dryRun: boolean;
}

export interface RuleTestResponse {
  scanned: number;
  normalized: number;
  passedDeterministicFilters: number;
  passedLlmFilters: number;
  rejectedReasons: Record<string, number>;
  rejectedItems: {
    source: string;
    externalId: string;
    title: string;
    game: string;
    url: string;
    reason: string;
    stage: "deterministic" | "llm" | "deduplicate" | string;
    llmFeedback?: string;
  }[];
  items: ModItem[];
}

// ── Rule Editor Draft Types ──────────────────────────────────

export interface RuleEditorDraft {
  name: string;
  enabled: boolean;
  intervalMinutes: number;
  commonFilters: CommonRuleFilters;
  nexusmodsDraft: NexusModsRuleConfig;
  loverslabDraft: LoversLabRuleConfig;
  notification: NotificationConfig;
}

export interface WatchRuleCreate {
  name: string;
  enabled: boolean;
  intervalMinutes: number;
  source: ModSource;
  sourceConfig: NexusModsRuleConfig | LoversLabRuleConfig;
  filters: CommonRuleFilters;
  notification: NotificationConfig;
}

// ── Notification Center ───────────────────────────────────────

export interface NotificationItem {
  id: number;
  channel: string;
  recipient: string;
  subject: string;
  body: string;
  status: string;
  error_message?: string;
  sent_at?: string;
  created_at: string;
  read: boolean;
}

export interface NotificationList {
  items: NotificationItem[];
  total: number;
}
