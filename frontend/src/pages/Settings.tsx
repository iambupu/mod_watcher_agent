import React, { useState, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Settings as SettingsIcon, Search, LayoutDashboard, Heart, Bell, SlidersHorizontal, FileText, Loader2, PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

import { NotificationSettings } from "@/components/NotificationSettings";
import { DEFAULT_PROVIDER_BASE_URLS, fetchSettings, updateSettings, testLlmProviders, testTelegram, testDiscord, exportSettings, importSettings, type LlmProviderTestResult } from "@/api/settings";
import type { UserSettings, UILanguage, LlmProvider, LlmProviderConfig } from "@/types";

const NavLink: React.FC<{ href: string; icon: React.ReactNode; label: string; active?: boolean }> = ({
  href,
  icon,
  label,
  active,
}) => (
  <a
    href={href}
    className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      active ? "bg-blue-50 text-blue-700" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
    }`}
  >
    {icon}
    {label}
  </a>
);

const PROVIDER_OPTIONS: { provider: LlmProvider; label: string; defaultModel: string }[] = [
  { provider: "ollama", label: "Ollama (Local)", defaultModel: "qwen3:8b" },
  { provider: "openai", label: "OpenAI", defaultModel: "gpt-4o-mini" },
  { provider: "anthropic", label: "Anthropic", defaultModel: "claude-3-5-haiku-latest" },
  { provider: "gemini", label: "Google Gemini", defaultModel: "gemini-2.0-flash" },
  { provider: "groq", label: "Groq", defaultModel: "mixtral-8x7b-32768" },
  { provider: "deepseek", label: "DeepSeek", defaultModel: "deepseek-chat" },
  { provider: "openrouter", label: "OpenRouter", defaultModel: "gpt-4o-mini" },
];

function normalizeProviders(providers: LlmProviderConfig[]): LlmProviderConfig[] {
  const byProvider = new Map(providers.map((p) => [p.provider, p]));
  return PROVIDER_OPTIONS.map((option, index) => {
    const existing = byProvider.get(option.provider);
    return {
      provider: option.provider,
      enabled: existing?.enabled ?? option.provider === "ollama",
      priority: existing?.priority ?? index + 1,
      model: existing?.model || option.defaultModel,
      apiKey: existing?.apiKey || "",
      baseUrl: existing?.baseUrl || DEFAULT_PROVIDER_BASE_URLS[option.provider],
    };
  }).sort((a, b) => a.priority - b.priority);
}

const Settings: React.FC = () => {
  const { t, i18n } = useTranslation();
  const queryClient = useQueryClient();

  const {
    data: settings,
    isLoading,
    isError,
  } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
  });

  const [uiLanguage, setUILanguage] = useState<UILanguage>("zh-CN");
  const [summaryLanguage, setSummaryLanguage] = useState<UILanguage>("zh-CN");
  const [summaryReportInterval, setSummaryReportInterval] = useState(0);
  const [summaryReportPrompt, setSummaryReportPrompt] = useState("");
  const [nexusApiKey, setNexusApiKey] = useState("");
  const [llmProvider, setLlmProvider] = useState<LlmProvider>("openai");
  const [llmModel, setLlmModel] = useState("");
  const [llmApiKey, setLlmApiKey] = useState("");
  const [llmBaseUrl, setLlmBaseUrl] = useState("");
  const [llmProviders, setLlmProviders] = useState<LlmProviderConfig[]>(normalizeProviders([]));
  const [llmTestResults, setLlmTestResults] = useState<LlmProviderTestResult[]>([]);
  const [testingLlm, setTestingLlm] = useState(false);
  const [telegramEnabled, setTelegramEnabled] = useState(false);
  const [telegramBotToken, setTelegramBotToken] = useState("");
  const [telegramChatId, setTelegramChatId] = useState("");
  const [discordEnabled, setDiscordEnabled] = useState(false);
  const [discordWebhookUrl, setDiscordWebhookUrl] = useState("");
  const [autoStart, setAutoStart] = useState(false);
  const [notificationsEnabled, setNotificationsEnabled] = useState(true);
  const [systemNotificationsEnabled, setSystemNotificationsEnabled] = useState(true);
  const [databasePath, setDatabasePath] = useState("");
  const [proxyEnabled, setProxyEnabled] = useState(false);
  const [proxyType, setProxyType] = useState<"http" | "socks5">("http");
  const [proxyHost, setProxyHost] = useState("");
  const [proxyPort, setProxyPort] = useState("");
  const [proxyUsername, setProxyUsername] = useState("");
  const [proxyPassword, setProxyPassword] = useState("");
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [proxyErrors, setProxyErrors] = useState<{ host?: string; port?: string }>({});
  const [importMsg, setImportMsg] = useState<{ type: "success" | "error"; text: string } | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(true);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (settings) {
      setUILanguage(settings.uiLanguage);
      i18n.changeLanguage(settings.uiLanguage);
      setSummaryLanguage(settings.summaryLanguage);
      setSummaryReportInterval(settings.summaryReportIntervalMinutes);
      setSummaryReportPrompt(settings.summaryReportPrompt);
      setNexusApiKey(settings.nexusApiKey);
      setLlmProvider(settings.llmProvider);
      setLlmModel(settings.llmModel);
      setLlmApiKey(settings.llmApiKey);
      setLlmBaseUrl(settings.llmBaseUrl);
      setLlmProviders(normalizeProviders(settings.llmProviders));
      setTelegramEnabled(settings.telegramEnabled);
      setTelegramBotToken(settings.telegramBotToken);
      setTelegramChatId(settings.telegramChatId);
      setDiscordEnabled(settings.discordEnabled);
      setDiscordWebhookUrl(settings.discordWebhookUrl);
      setAutoStart(settings.autoStart);
      setNotificationsEnabled(settings.notificationsEnabled);
      setSystemNotificationsEnabled(settings.systemNotificationsEnabled);
      setDatabasePath(settings.databasePath);
      setProxyEnabled(settings.proxyEnabled);
      setProxyType(settings.proxyType);
      setProxyHost(settings.proxyHost);
      setProxyPort(settings.proxyPort);
      setProxyUsername(settings.proxyUsername);
      setProxyPassword(settings.proxyPassword);
    }
  }, [settings]);

  const mutation = useMutation({
    mutationFn: updateSettings,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["settings"] });
      setSaved(true);
      setSaveError(null);
      setTimeout(() => setSaved(false), 3000);
    },
    onError: (err: Error) => {
      setSaveError(err.message);
    },
  });

  const handleLanguageChange = (lang: UILanguage) => {
    setUILanguage(lang);
    i18n.changeLanguage(lang);
  };

  const buildSettingsPayload = (): Partial<UserSettings> => {
    const payload: Partial<UserSettings> = {
      uiLanguage,
      summaryLanguage,
      summaryReportIntervalMinutes: summaryReportInterval,
      summaryReportPrompt,
      nexusApiKey,
      llmProvider,
      llmModel,
      llmApiKey,
      llmBaseUrl,
      llmProviders,
      telegramEnabled,
      telegramBotToken,
      telegramChatId,
      discordEnabled,
      discordWebhookUrl,
      autoStart,
      notificationsEnabled,
      systemNotificationsEnabled,
      databasePath,
      proxyEnabled,
      proxyType,
      proxyHost,
      proxyPort,
      proxyUsername,
      proxyPassword,
    };
    return payload;
  };

  const handleSaveSettings = () => {
    if (proxyEnabled) {
      const errs: { host?: string; port?: string } = {};
      if (!proxyHost.trim()) errs.host = t("settings.required") || "Required";
      if (!proxyPort.trim()) errs.port = t("settings.required") || "Required";
      setProxyErrors(errs);
      if (Object.keys(errs).length > 0) return;
    }
    setProxyErrors({});
    mutation.mutate(buildSettingsPayload());
  };

  const handleExport = async () => {
    try {
      await exportSettings();
    } catch {
      alert(t("settings.exportError"));
    }
  };

  const handleImport = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const result = await importSettings(file);
      setImportMsg({ type: "success", text: t("settings.importSuccess", { count: result.imported }) });
      setSaved(true);
      setTimeout(() => { setSaved(false); setImportMsg(null); }, 3000);
      queryClient.invalidateQueries({ queryKey: ["settings"] });
    } catch {
      setImportMsg({ type: "error", text: t("settings.importError") });
    }
    if (fileInputRef.current) fileInputRef.current.value = "";
  };

  const updateProvider = (provider: LlmProvider, patch: Partial<LlmProviderConfig>) => {
    setLlmProviders((current) => current.map((item) => (
      item.provider === provider ? { ...item, ...patch } : item
    )));
  };

  const moveProvider = (provider: LlmProvider, direction: -1 | 1) => {
    setLlmProviders((current) => {
      const sorted = [...current].sort((a, b) => a.priority - b.priority);
      const index = sorted.findIndex((item) => item.provider === provider);
      const target = index + direction;
      if (index < 0 || target < 0 || target >= sorted.length) return current;
      [sorted[index], sorted[target]] = [sorted[target], sorted[index]];
      return sorted.map((item, idx) => ({ ...item, priority: idx + 1 }));
    });
  };

  const handleTestLlmProviders = async () => {
    setTestingLlm(true);
    try {
      const result = await testLlmProviders(llmProviders);
      setLlmTestResults(result.results);
    } catch (err) {
      setLlmTestResults([{ provider: "all", success: false, latency_ms: null, message: (err as Error).message }]);
    } finally {
      setTestingLlm(false);
    }
  };

  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <Loader2 className="animate-spin text-blue-500" size={32} />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <div className="text-center space-y-4">
          <p className="text-red-500 text-lg font-medium">{t("settings.loadError")}</p>
          <p className="text-gray-500 text-sm">{t("settings.loadErrorHint")}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-4 py-2 bg-blue-500 text-white rounded-lg text-sm hover:bg-blue-600"
          >
            {t("settings.retry")}
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        {sidebarOpen && (
        <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
          <div className="px-6 py-4 border-b border-gray-200">
            <div className="flex items-center gap-2">
              <img src="/mwlogo.png" alt="Mod Watcher" className="h-12 w-auto" />
              <span className="text-lg font-bold text-gray-900">Mod Watcher</span>
              <button
                type="button"
                onClick={() => setSidebarOpen(false)}
                className="ml-auto rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900"
                title={t("settings.hideSidebar")}
                aria-label={t("settings.hideSidebar")}
              >
                <PanelLeftClose size={18} />
              </button>
            </div>
          </div>

          <nav className="flex-1 px-3 py-4 space-y-1">
            <NavLink href="/" icon={<LayoutDashboard size={18} />} label={t("nav.dashboard")} />
            <NavLink href="/discover" icon={<Search size={18} />} label={t("nav.discover")} />
            <NavLink href="/favorites" icon={<Heart size={18} />} label={t("nav.favorites")} />
            <NavLink href="/updates" icon={<Bell size={18} />} label={t("nav.updates")} />
            <NavLink href="/rules" icon={<SlidersHorizontal size={18} />} label={t("nav.rules")} />
            <NavLink href="/logs" icon={<FileText size={18} />} label={t("nav.logs")} />
            <NavLink href="/settings" icon={<SettingsIcon size={18} />} label={t("nav.settings")} active />
          </nav>

        </aside>
        )}

        <main className="flex-1 overflow-y-auto p-6">
          <div className="mb-6 flex items-center gap-3">
            {!sidebarOpen && (
              <button
                type="button"
                onClick={() => setSidebarOpen(true)}
                className="rounded-md border border-gray-300 bg-white p-2 text-gray-600 hover:bg-gray-50 hover:text-gray-900"
                title={t("settings.showSidebar")}
                aria-label={t("settings.showSidebar")}
              >
                <PanelLeftOpen size={18} />
              </button>
            )}
            <h2 className="text-2xl font-bold text-gray-900">{t("settings.title")}</h2>
          </div>

          {isError && (
            <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
              {t("common.error")}
            </div>
          )}

          <div className="space-y-6 max-w-2xl">
            <Card>
              <CardHeader>
                <h3 className="font-semibold">{t("settings.uiLanguage")}</h3>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-4">
                  <select
                    value={uiLanguage}
                    onChange={(e) => handleLanguageChange(e.target.value as UILanguage)}
                    className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                  >
                    <option value="zh-CN">中文</option>
                    <option value="en-US">English</option>
                    <option value="ja-JP">日本語</option>
                  </select>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent>
                <div>
                  <div>
                    <label className="block text-sm font-medium mb-2">{t("settings.summaryLanguage")}</label>
                    <select
                      value={summaryLanguage}
                      onChange={(e) => setSummaryLanguage(e.target.value as UILanguage)}
                      className="w-full rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      <option value="zh-CN">中文</option>
                      <option value="en-US">English</option>
                      <option value="ja-JP">日本語</option>
                    </select>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <h3 className="font-semibold">{t("settings.summaryReport")}</h3>
              </CardHeader>
              <CardContent className="space-y-3">
                <Input
                  label={t("settings.summaryReportInterval")}
                  type="number"
                  min={0}
                  max={10080}
                  value={summaryReportInterval}
                  onChange={(e) => setSummaryReportInterval(Number(e.target.value))}
                />
                <Input
                  label={t("settings.summaryReportPrompt")}
                  value={summaryReportPrompt}
                  onChange={(e) => setSummaryReportPrompt(e.target.value)}
                  placeholder={t("settings.summaryReportPromptPlaceholder")}
                />
                <p className="text-xs text-gray-500">{t("settings.summaryReportHint")}</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <h3 className="font-semibold">{t("settings.credentials")}</h3>
              </CardHeader>
              <CardContent>
                <div className="space-y-4">
                  <Input
                    label={t("settings.nexusApiKey")}
                    type="password"
                    value={nexusApiKey}
                    onChange={(e) => setNexusApiKey(e.target.value)}
                    placeholder="nexusmods.com personal API key"
                    help={{ titleKey: "settings.help.nexusKey.title", stepsKey: "settings.help.nexusKey.steps", stepCount: 4 }}
                  />
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <div className="flex items-center justify-between gap-3">
                  <h3 className="font-semibold">{t("settings.llmProvider")}</h3>
                  <Button size="sm" variant="outline" onClick={handleTestLlmProviders} disabled={testingLlm}>
                    {testingLlm ? t("common.loading") : t("settings.testLlmProviders")}
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="space-y-4">
                <p className="text-xs text-gray-500">{t("settings.llmProviderPriorityHint")}</p>
                <div className="space-y-3">
                  {[...llmProviders].sort((a, b) => a.priority - b.priority).map((provider, index) => {
                    const option = PROVIDER_OPTIONS.find((item) => item.provider === provider.provider);
                    const result = llmTestResults.find((item) => item.provider === provider.provider);
                    return (
                      <div key={provider.provider} className="rounded-lg border border-gray-200 p-3">
                        <div className="mb-3 flex flex-wrap items-center gap-2">
                          <input
                            type="checkbox"
                            checked={provider.enabled}
                            onChange={(e) => updateProvider(provider.provider, { enabled: e.target.checked })}
                            className="rounded"
                          />
                          <span className="text-sm font-semibold text-gray-900">{provider.priority}. {option?.label ?? provider.provider}</span>
                          <button type="button" onClick={() => moveProvider(provider.provider, -1)} disabled={index === 0} className="ml-auto rounded border px-2 py-1 text-xs disabled:opacity-40">
                            {t("settings.priorityUp")}
                          </button>
                          <button type="button" onClick={() => moveProvider(provider.provider, 1)} disabled={index === llmProviders.length - 1} className="rounded border px-2 py-1 text-xs disabled:opacity-40">
                            {t("settings.priorityDown")}
                          </button>
                          {result && (
                            <span
                              className={`rounded px-2 py-1 text-xs ${result.success ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}
                              title={result.message}
                            >
                              {result.success ? t("settings.testOk") : t("settings.testFailed")}
                              {result.latency_ms !== null ? ` ${result.latency_ms}ms` : ""}
                            </span>
                          )}
                        </div>
                        <div className="grid gap-3 md:grid-cols-3">
                          <Input
                            label={t("settings.llmModel")}
                            value={provider.model}
                            onChange={(e) => updateProvider(provider.provider, { model: e.target.value })}
                            placeholder={option?.defaultModel ?? t("settings.llmModelPlaceholder")}
                          />
                          <Input
                            label={t("settings.llmApiKey")}
                            type="password"
                            value={provider.apiKey}
                            onChange={(e) => updateProvider(provider.provider, { apiKey: e.target.value })}
                            placeholder={provider.provider === "ollama" ? t("settings.optional") : t("settings.llmApiKeyPlaceholder")}
                          />
                          <Input
                            label={t("settings.llmBaseUrl")}
                            value={provider.baseUrl}
                            onChange={(e) => updateProvider(provider.provider, { baseUrl: e.target.value })}
                            placeholder={DEFAULT_PROVIDER_BASE_URLS[provider.provider]}
                          />
                        </div>
                        <p className="mt-2 text-xs text-gray-500">
                          {t("settings.defaultBaseUrl")}: {DEFAULT_PROVIDER_BASE_URLS[provider.provider]}
                        </p>
                        {result && (
                          <p className={`mt-1 rounded-md px-2 py-1 text-xs ${result.success ? "bg-green-50 text-green-700" : "bg-red-50 text-red-700"}`}>
                            {result.success ? "测试成功" : "失败原因"}: {result.message}
                          </p>
                        )}
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardContent className="py-4">
                <NotificationSettings
                  telegramEnabled={telegramEnabled}
                  telegramBotToken={telegramBotToken}
                  telegramChatId={telegramChatId}
                  discordEnabled={discordEnabled}
                  discordWebhookUrl={discordWebhookUrl}
                  notificationsEnabled={notificationsEnabled}
                  systemNotificationsEnabled={systemNotificationsEnabled}
                  onTelegramEnabledChange={setTelegramEnabled}
                  onTelegramBotTokenChange={setTelegramBotToken}
                  onTelegramChatIdChange={setTelegramChatId}
                  onDiscordEnabledChange={setDiscordEnabled}
                  onDiscordWebhookUrlChange={setDiscordWebhookUrl}
                  onNotificationsEnabledChange={setNotificationsEnabled}
                  onSystemNotificationsEnabledChange={setSystemNotificationsEnabled}
                  onTestTelegram={async () => {
                    try { const r = await testTelegram(); alert(r.message); } catch { alert("Test failed"); }
                  }}
                  onTestDiscord={async () => {
                    try { const r = await testDiscord(); alert(r.message); } catch { alert("Test failed"); }
                  }}
                />
              </CardContent>
            </Card>

            {importMsg && (
              <div className={`p-3 border rounded-lg text-sm ${
                importMsg.type === "success"
                  ? "bg-green-50 border-green-200 text-green-800"
                  : "bg-red-50 border-red-200 text-red-800"
              }`}>
                {importMsg.text}
              </div>
            )}

            <Card>
              <CardHeader>
                <h3 className="font-semibold">{t("settings.autoStart")}</h3>
              </CardHeader>
              <CardContent>
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={autoStart}
                    onChange={(e) => setAutoStart(e.target.checked)}
                    className="w-5 h-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <div>
                    <p className="text-sm font-medium text-gray-700">{t("settings.autoStartLabel")}</p>
                    <p className="text-xs text-gray-500">{t("settings.autoStartHint")}</p>
                  </div>
                </label>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <h3 className="font-semibold">{t("settings.databasePath")}</h3>
              </CardHeader>
              <CardContent className="space-y-2">
                <Input
                  value={databasePath}
                  onChange={(e) => setDatabasePath(e.target.value)}
                  placeholder="sqlite:///./mod_watcher.db"
                />
                <p className="text-xs text-amber-600">{t("settings.databasePathHint")}</p>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <h3 className="font-semibold">{t("settings.proxy")}</h3>
              </CardHeader>
              <CardContent className="space-y-4">
                <label className="flex items-center gap-3 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={proxyEnabled}
                    onChange={(e) => setProxyEnabled(e.target.checked)}
                    className="w-5 h-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  <span className="text-sm font-medium text-gray-700">{t("settings.proxyEnabled")}</span>
                </label>
                {proxyEnabled && (
                  <div className="space-y-3 pl-8">
                    <select
                      value={proxyType}
                      onChange={(e) => setProxyType(e.target.value as "http" | "socks5")}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm"
                    >
                      <option value="http">HTTP</option>
                      <option value="socks5">SOCKS5</option>
                    </select>
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <Input label={`${t("settings.proxyHost")} *`} value={proxyHost} onChange={(e) => { setProxyHost(e.target.value); setProxyErrors((p) => ({ ...p, host: undefined })); }} placeholder="127.0.0.1" required error={proxyErrors.host} />
                        {!proxyErrors.host && <p className="text-xs text-amber-600 mt-1">启用代理后必须填写</p>}
                      </div>
                      <div>
                        <Input label={`${t("settings.proxyPort")} *`} value={proxyPort} onChange={(e) => { setProxyPort(e.target.value); setProxyErrors((p) => ({ ...p, port: undefined })); }} placeholder="7890" required error={proxyErrors.port} />
                        {!proxyErrors.port && <p className="text-xs text-amber-600 mt-1">启用代理后必须填写</p>}
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-3">
                      <Input label={t("settings.proxyUsername")} value={proxyUsername} onChange={(e) => setProxyUsername(e.target.value)} placeholder={t("settings.optional")} />
                      <Input label={t("settings.proxyPassword")} type="password" value={proxyPassword} onChange={(e) => setProxyPassword(e.target.value)} placeholder={t("settings.optional")} />
                    </div>
                    <p className="text-xs text-gray-500">{t("settings.proxyHint")}</p>
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <h3 className="font-semibold">{t("settings.data")}</h3>
              </CardHeader>
              <CardContent>
                <div className="flex items-center gap-3">
                  <Button onClick={handleExport}>{t("settings.export")}</Button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    accept=".json"
                    className="hidden"
                    onChange={handleImport}
                  />
                  <Button onClick={() => fileInputRef.current?.click()}>{t("settings.import")}</Button>
                </div>
              </CardContent>
            </Card>

            <div className="flex items-center gap-3">
              <Button onClick={handleSaveSettings} disabled={mutation.isPending}>
                {mutation.isPending ? t("common.loading") : t("settings.save")}
              </Button>
              {saved && (
                <div className="px-3 py-2 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
                  {t("settings.saved")}
                </div>
              )}
              {saveError && (
                <div className="px-3 py-2 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
                  {t("settings.saveError", { error: saveError })}
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default Settings;
