import { afterEach, describe, expect, it, vi } from "vitest";

import { exportSettings, fetchSettings, importSettings } from "@/api/settings";
import { ApiError } from "@/api/client";

describe("settings API mapping", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("drops unknown LLM providers and falls back to a known primary provider", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        settings: {
          llm_provider: "unknown-provider",
          llm_model: "legacy-model",
          llm_api_key: "",
          llm_base_url: "",
          llm_providers_json: JSON.stringify([
            {
              provider: "unknown-provider",
              enabled: true,
              priority: 1,
              model: "legacy-model",
              api_key: "",
              base_url: "",
            },
            {
              provider: "openai",
              enabled: true,
              priority: 2,
              model: "gpt-4o-mini",
              api_key: "",
              base_url: "",
            },
          ]),
        },
      }),
    } as Response);

    const settings = await fetchSettings();

    expect(settings.llmProvider).toBe("openai");
    expect(settings.llmProviders).toHaveLength(1);
    expect(settings.llmProviders[0]).toMatchObject({
      provider: "openai",
      model: "gpt-4o-mini",
    });
  });

  it("falls back when backend LLM provider config is non-array JSON", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        settings: {
          llm_provider: "openai",
          llm_model: "legacy-model",
          llm_api_key: "legacy-key",
          llm_base_url: "https://api.openai.com/v1",
          llm_providers_json: "{}",
        },
      }),
    } as Response);

    const settings = await fetchSettings();

    expect(settings.llmProviders).toEqual([
      {
        provider: "openai",
        enabled: true,
        priority: 1,
        model: "legacy-model",
        apiKey: "legacy-key",
        baseUrl: "https://api.openai.com/v1",
      },
    ]);
  });

  it("parses string booleans in backend LLM provider config", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        settings: {
          llm_provider: "openai",
          llm_model: "",
          llm_api_key: "",
          llm_base_url: "",
          llm_providers_json: JSON.stringify([
            {
              provider: "openai",
              enabled: "false",
              priority: 1,
              model: "gpt-4o-mini",
              api_key: "",
              base_url: "",
            },
          ]),
        },
      }),
    } as Response);

    const settings = await fetchSettings();

    expect(settings.llmProviders[0].enabled).toBe(false);
  });

  it("normalizes boolean-like top-level backend settings", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        settings: {
          llm_provider: "openai",
          llm_model: "",
          llm_api_key: "",
          llm_base_url: "",
          llm_providers_json: "[]",
          loverslab_search_scrape_enabled: "0",
          telegram_enabled: "1",
          discord_enabled: true,
          system_notifications_enabled: "false",
          auto_start: "true",
          notifications_enabled: false,
          proxy_enabled: "yes",
          allow_lan: "no",
        },
      }),
    } as Response);

    const settings = await fetchSettings();

    expect(settings.loverslabSearchScrapeEnabled).toBe(false);
    expect(settings.telegramEnabled).toBe(true);
    expect(settings.discordEnabled).toBe(true);
    expect(settings.systemNotificationsEnabled).toBe(false);
    expect(settings.autoStart).toBe(true);
    expect(settings.notificationsEnabled).toBe(false);
    expect(settings.proxyEnabled).toBe(true);
    expect(settings.allowLan).toBe(false);
  });

  it("clamps numeric settings from backend values before exposing them to the UI", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        settings: {
          summary_report_interval_minutes: "20000",
          watchdog_check_interval_minutes: "999",
          watchdog_grace_minutes: "0",
          watchdog_max_catchup_per_run: "abc",
          ui_language: "bad-locale",
          summary_language: "bad-locale",
          summary_mode: "bad-mode",
          loverslab_search_scrape_engine: "bad-engine",
          proxy_type: "ftp",
          access_profile: "public",
          llm_provider: "openai",
          llm_model: "",
          llm_api_key: "",
          llm_base_url: "",
          llm_providers_json: JSON.stringify([
            {
              provider: "openai",
              enabled: true,
              priority: 0,
              model: "gpt-4o-mini",
              api_key: "",
              base_url: "",
            },
          ]),
        },
      }),
    } as Response);

    const settings = await fetchSettings();

    expect(settings.summaryReportIntervalMinutes).toBe(10080);
    expect(settings.watchdogCheckIntervalMinutes).toBe(180);
    expect(settings.watchdogGraceMinutes).toBe(1);
    expect(settings.watchdogMaxCatchupPerRun).toBe(3);
    expect(settings.llmProviders[0].priority).toBe(1);
    expect(settings.uiLanguage).toBe("zh-CN");
    expect(settings.summaryLanguage).toBe("zh-CN");
    expect(settings.summaryMode).toBe("bilingual");
    expect(settings.loverslabSearchScrapeEngine).toBe("duckduckgo");
    expect(settings.proxyType).toBe("http");
    expect(settings.accessProfile).toBe("local_relaxed");
  });

  it("preserves backend error detail when export fails", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 422,
      statusText: "Unprocessable Entity",
      json: async () => ({ detail: "export disabled" }),
    } as Response);

    await expect(exportSettings()).rejects.toMatchObject({
      status: 422,
      detail: "export disabled",
      message: "API Error 422: export disabled",
    } satisfies Partial<ApiError>);
  });

  it("rejects invalid local settings JSON with a stable message", async () => {
    const file = { text: async () => "not json" } as File;

    await expect(importSettings(file)).rejects.toThrow("Invalid JSON file");
  });

  it("rejects non-object local settings JSON before posting", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    const file = { text: async () => "[]" } as File;

    await expect(importSettings(file)).rejects.toThrow("Settings import file must be a JSON object");
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
