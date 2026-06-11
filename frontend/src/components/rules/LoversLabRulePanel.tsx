// 中文注释：提供规则编辑器里的 LoversLabRulePanel 表单组件。

import React, { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  checkLoversLabSession,
  fetchLoversLabBrowserStatus,
  installLoversLabChromium,
  openLoversLabLogin,
  saveLoversLabSnapshot,
  testLoversLabCategory,
  type LoversLabBrowserStatus,
  type LoversLabCategoryTestResult,
  type LoversLabSessionResult,
  type LoversLabSnapshotResult,
} from "@/api/loverslab-browser";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { LoversLabRuleConfig } from "@/types";
import { parseIntegerInput } from "@/utils/numberInput";

type UpdateDetection = NonNullable<LoversLabRuleConfig["updateDetection"]>;

export const LoversLabRulePanel: React.FC = () => {
  const { t } = useTranslation();
  const loverslabDraft = useRuleEditorStore((s) => s.draft.loverslabDraft);
  const updateLoversLabConfig = useRuleEditorStore((s) => s.updateLoversLabConfig);
  const [browserStatus, setBrowserStatus] = useState<LoversLabBrowserStatus | null>(null);
  const [sessionResult, setSessionResult] = useState<LoversLabSessionResult | null>(null);
  const [testResult, setTestResult] = useState<LoversLabCategoryTestResult | null>(null);
  const [snapshotResult, setSnapshotResult] = useState<LoversLabSnapshotResult | null>(null);
  const [browserBusy, setBrowserBusy] = useState(false);
  const [testBusy, setTestBusy] = useState(false);
  const [snapshotBusy, setSnapshotBusy] = useState(false);
  const [installBusy, setInstallBusy] = useState(false);
  const [error, setError] = useState("");
  const accessMode = loverslabDraft.accessMode || "rss";
  const usesBrowserAccess = accessMode !== "rss";
  const usesRssAccess = accessMode !== "page";

  useEffect(() => {
    if (!usesBrowserAccess) {
      setBrowserStatus(null);
      setSessionResult(null);
      return;
    }
    let cancelled = false;
    fetchLoversLabBrowserStatus()
      .then((status) => {
        if (!cancelled) setBrowserStatus(status);
      })
      .catch((exc: Error) => {
        if (!cancelled) setError(exc.message);
      });
    return () => {
      cancelled = true;
    };
  }, [usesBrowserAccess]);

  const updateDetectionOptions: { value: UpdateDetection; labelKey: string }[] = [
    { value: "published_time", labelKey: "rules.loverslab.updateDetection.publishedTime" },
    { value: "updated_time", labelKey: "rules.loverslab.updateDetection.updatedTime" },
    { value: "page_hash", labelKey: "rules.loverslab.updateDetection.pageHash" },
  ];

  const accessModeOptions: { value: NonNullable<LoversLabRuleConfig["accessMode"]>; labelKey: string }[] = [
    { value: "rss", labelKey: "rules.loverslab.accessModeRss" },
    { value: "page", labelKey: "rules.loverslab.accessModePage" },
    { value: "both", labelKey: "rules.loverslab.accessModeBoth" },
  ];

  const statusText = sessionResult?.status || browserStatus?.lastCheckStatus || "unknown";
  const pageUrlsText = (loverslabDraft.pageUrls || []).join("\n");
  const firstPageUrl = (loverslabDraft.pageUrls || [])[0] || "";
  const browserLabel = !browserStatus?.browserInstalled
    ? t("rules.loverslab.statusMissing")
    : browserStatus.browserName
      ? browserStatus.browserSource === "system"
        ? t("rules.loverslab.statusSystemBrowser", { browser: browserStatus.browserName })
        : browserStatus.browserName
      : t("rules.loverslab.statusInstalled");

  const runBrowserAction = async (action: "open-login" | "check-session") => {
    setBrowserBusy(true);
    setError("");
    try {
      const result =
        action === "open-login" ? await openLoversLabLogin() : await checkLoversLabSession();
      setSessionResult(result);
      setBrowserStatus(await fetchLoversLabBrowserStatus());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBrowserBusy(false);
    }
  };

  const runCategoryTest = async () => {
    if (!firstPageUrl) {
      setError(t("rules.loverslab.browserTestMissingUrl"));
      return;
    }
    setTestBusy(true);
    setError("");
    setSnapshotResult(null);
    try {
      setTestResult(
        await testLoversLabCategory({
          url: firstPageUrl,
          gameLabel: loverslabDraft.gameLabel || "LoversLab",
          maxItems: 20,
        }),
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setTestBusy(false);
    }
  };

  const runSnapshotSave = async () => {
    if (!firstPageUrl) {
      setError(t("rules.loverslab.browserTestMissingUrl"));
      return;
    }
    setSnapshotBusy(true);
    setError("");
    try {
      setSnapshotResult(
        await saveLoversLabSnapshot({
          url: firstPageUrl,
          profileName: loverslabDraft.browserProfile || "loverslab",
        }),
      );
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setSnapshotBusy(false);
    }
  };

  const runChromiumInstall = async () => {
    setInstallBusy(true);
    setError("");
    try {
      const result = await installLoversLabChromium();
      if (!result.success) {
        setError(result.stderr || result.message);
      }
      setBrowserStatus(await fetchLoversLabBrowserStatus());
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setInstallBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="loverslab-game-label" className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.gameLabel")}
        </label>
        <p className="text-xs text-gray-500">{t("rules.loverslab.ruleGuideLine4")}</p>
        <input
          id="loverslab-game-label"
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          placeholder={t("rules.loverslab.gameLabelPlaceholder")}
          required
          value={loverslabDraft.gameLabel || ""}
          onChange={(e) => updateLoversLabConfig({ gameLabel: e.target.value })}
        />
      </div>

      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        <p className="font-medium">{t("rules.loverslab.ruleGuideTitle")}</p>
        <p>{t("rules.loverslab.ruleGuideLine1")}</p>
        <p>{t("rules.loverslab.ruleGuideLine2")}</p>
        <p>{t("rules.loverslab.ruleGuideLine3")}</p>
      </div>

      {usesBrowserAccess ? (
        <div className="flex flex-col gap-2 rounded-md border border-gray-200 bg-gray-50 p-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <p className="text-sm font-medium text-gray-800">{t("rules.loverslab.browserAccess")}</p>
              <p className="text-xs text-gray-500">
                {t("rules.loverslab.browserStatus", {
                  browser: browserLabel,
                  profile: browserStatus?.profileExists
                    ? t("rules.loverslab.statusInitialized")
                    : t("rules.loverslab.statusNotInitialized"),
                  session: t(`rules.loverslab.browserStatus.${statusText}`, { defaultValue: statusText }),
                })}
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {!browserStatus?.browserInstalled ? (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  disabled={installBusy}
                  onClick={runChromiumInstall}
                >
                  {installBusy ? t("rules.loverslab.installingChromium") : t("rules.loverslab.installChromium")}
                </Button>
              ) : null}
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={browserBusy}
                onClick={() => runBrowserAction("open-login")}
              >
                {t("rules.loverslab.openLoginBrowser")}
              </Button>
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={browserBusy}
                onClick={() => runBrowserAction("check-session")}
              >
                {t("rules.loverslab.checkSession")}
              </Button>
            </div>
          </div>
          {sessionResult?.error ? <p className="text-xs text-red-600">{sessionResult.error}</p> : null}
          <p className="text-xs text-gray-500">{t("rules.loverslab.browserProfileHelp")}</p>
          {sessionResult ? (
            <p className="text-xs text-gray-500">
              {t("rules.loverslab.sessionChecked", {
                title: sessionResult.title || "-",
                finalUrl: sessionResult.finalUrl || "-",
              })}
            </p>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.accessMode")}
        </label>
        <select
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={accessMode}
          onChange={(e) =>
            updateLoversLabConfig({
              accessMode: e.target.value as NonNullable<LoversLabRuleConfig["accessMode"]>,
            })
          }
        >
          {accessModeOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
        <p className="text-xs text-gray-500">
          {usesBrowserAccess ? t("rules.loverslab.pageModeHelp") : t("rules.loverslab.rssModeHelp")}
        </p>
      </div>

      {usesRssAccess ? (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">
            {t("rules.loverslab.feedUrls")}
          </label>
          <p className="text-xs text-gray-500">{t("rules.loverslab.feedUrlsHelp")}</p>
          <p className="text-xs text-gray-500">{t("rules.loverslab.ruleGuideLine5")}</p>
          <textarea
            className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            rows={3}
            placeholder={t("rules.loverslab.feedUrlsPlaceholder")}
            value={(loverslabDraft.feedUrls || []).join("\n")}
            onChange={(e) =>
              updateLoversLabConfig({
                feedUrls: e.target.value
                  .split("\n")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>
      ) : null}

      {usesBrowserAccess ? (
        <div className="flex flex-col gap-2">
          <label className="text-sm font-medium text-gray-700">
            {t("rules.loverslab.pageUrls")}
          </label>
          <p className="text-xs text-gray-500">{t("rules.loverslab.pageUrlsHelp")}</p>
          <textarea
            className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            rows={3}
            placeholder={t("rules.loverslab.pageUrlsPlaceholder")}
            value={pageUrlsText}
            onChange={(e) =>
              updateLoversLabConfig({
                pageUrls: e.target.value
                  .split("\n")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" variant="outline" size="sm" disabled={testBusy} onClick={runCategoryTest}>
              {testBusy ? t("rules.loverslab.testingCategory") : t("rules.loverslab.testCategory")}
            </Button>
            <Button type="button" variant="outline" size="sm" disabled={snapshotBusy} onClick={runSnapshotSave}>
              {snapshotBusy ? t("rules.loverslab.savingSnapshot") : t("rules.loverslab.saveSnapshot")}
            </Button>
            {testResult ? (
              <span className="text-xs text-gray-600">
                {t("rules.loverslab.testCategoryResult", {
                  status: t(`rules.loverslab.browserStatus.${testResult.status}`, {
                    defaultValue: testResult.status,
                  }),
                  count: testResult.itemsCount,
                })}
              </span>
            ) : null}
          </div>
          {testResult ? (
            <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs text-gray-600">
              <p>
                {t("rules.loverslab.testCategoryDebug", {
                  title: testResult.title || "-",
                  finalUrl: testResult.finalUrl || "-",
                })}
              </p>
              {testResult.status === "structure_changed" ? (
                <p className="mt-1 text-amber-700">{t("rules.loverslab.structureChangedHelp")}</p>
              ) : null}
              {testResult.error ? <p className="mt-1 text-red-600">{testResult.error}</p> : null}
            </div>
          ) : null}
          {snapshotResult ? (
            <p className="text-xs text-gray-500">
              {t("rules.loverslab.snapshotSaved", { path: snapshotResult.path })}
            </p>
          ) : null}
          {testResult?.items?.length ? (
            <div className="max-h-48 overflow-auto rounded-md border border-gray-200 bg-white">
              {testResult.items.slice(0, 5).map((item) => (
                <div key={item.fileId} className="border-b border-gray-100 px-3 py-2 last:border-b-0">
                  <p className="text-sm font-medium text-gray-800">{item.title}</p>
                  <p className="text-xs text-gray-500">
                    {item.author || "-"} · {item.updatedAt || "-"}
                  </p>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}

      {error ? <p className="text-xs text-red-600">{error}</p> : null}

      <Input
        label={t("rules.loverslab.updatedSinceDays")}
        type="number"
        min={1}
        max={365}
        placeholder={t("rules.loverslab.updatedSinceDaysPlaceholder")}
        value={loverslabDraft.updatedSinceDays ?? ""}
        onChange={(e) => {
          const value = parseIntegerInput(e.target.value, {
            min: 1,
            max: 365,
            allowEmpty: true,
          });
          if (value !== null) {
            updateLoversLabConfig({ updatedSinceDays: value });
          }
        }}
      />
      <p className="text-xs text-gray-500">
        {usesRssAccess
          ? t("rules.loverslab.updatedSinceDaysHelp")
          : t("rules.loverslab.pageUpdatedSinceDaysHelp")}
      </p>

      <Input
        label={t("rules.loverslab.maxItemsPerRun")}
        type="number"
        min={1}
        max={100}
        value={loverslabDraft.maxItemsPerRun ?? ""}
        onChange={(e) => {
          const value = parseIntegerInput(e.target.value, { min: 1, max: 100 });
          if (value != null) {
            updateLoversLabConfig({ maxItemsPerRun: value });
          }
        }}
      />
      <p className="text-xs text-gray-500">{t("rules.loverslab.maxItemsPerRunHelp")}</p>
      {usesRssAccess ? <p className="text-xs text-amber-700">{t("rules.loverslab.rssNotice")}</p> : null}

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.updateDetection")}
        </label>
        <select
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={loverslabDraft.updateDetection || "published_time"}
          onChange={(e) =>
            updateLoversLabConfig({
              updateDetection: e.target.value as UpdateDetection,
            })
          }
        >
          {updateDetectionOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey!)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
};
