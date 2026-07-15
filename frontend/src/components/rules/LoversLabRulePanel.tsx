// 中文注释：提供仅基于 RSS 的 LoversLab 规则配置表单。

import { useTranslation } from "react-i18next";

import { Input } from "@/components/ui/Input";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { LoversLabRuleConfig } from "@/types";
import { parseIntegerInput } from "@/utils/numberInput";

type UpdateDetection = NonNullable<LoversLabRuleConfig["updateDetection"]>;

export const LoversLabRulePanel = () => {
  const { t } = useTranslation();
  const loverslabDraft = useRuleEditorStore((s) => s.draft.loverslabDraft);
  const updateLoversLabConfig = useRuleEditorStore((s) => s.updateLoversLabConfig);
  const updateDetectionOptions: { value: UpdateDetection; labelKey: string }[] = [
    { value: "published_time", labelKey: "rules.loverslab.updateDetection.publishedTime" },
    { value: "updated_time", labelKey: "rules.loverslab.updateDetection.updatedTime" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-1">
        <label htmlFor="loverslab-game-label" className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.gameLabel")}
        </label>
        <p className="text-xs text-gray-500">{t("rules.loverslab.ruleGuideLine4")}</p>
        <input
          id="loverslab-game-label"
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          placeholder={t("rules.loverslab.gameLabelPlaceholder")}
          required
          value={loverslabDraft.gameLabel || ""}
          onChange={(event) => updateLoversLabConfig({ gameLabel: event.target.value })}
        />
      </div>

      <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        <p className="font-medium">{t("rules.loverslab.ruleGuideTitle")}</p>
        <p>{t("rules.loverslab.ruleGuideLine1")}</p>
        <p>{t("rules.loverslab.ruleGuideLine2")}</p>
        <p>{t("rules.loverslab.ruleGuideLine3")}</p>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.feedUrls")}
        </label>
        <p className="text-xs text-gray-500">{t("rules.loverslab.feedUrlsHelp")}</p>
        <p className="text-xs text-gray-500">{t("rules.loverslab.ruleGuideLine5")}</p>
        <textarea
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          rows={3}
          placeholder={t("rules.loverslab.feedUrlsPlaceholder")}
          value={(loverslabDraft.feedUrls || []).join("\n")}
          onChange={(event) =>
            updateLoversLabConfig({
              feedUrls: event.target.value
                .split("\n")
                .map((value) => value.trim())
                .filter(Boolean),
            })
          }
        />
      </div>

      <Input
        label={t("rules.loverslab.updatedSinceDays")}
        type="number"
        min={1}
        max={365}
        placeholder={t("rules.loverslab.updatedSinceDaysPlaceholder")}
        value={loverslabDraft.updatedSinceDays ?? ""}
        onChange={(event) => {
          const value = parseIntegerInput(event.target.value, {
            min: 1,
            max: 365,
            allowEmpty: true,
          });
          if (value !== null) updateLoversLabConfig({ updatedSinceDays: value });
        }}
      />
      <p className="text-xs text-gray-500">{t("rules.loverslab.updatedSinceDaysHelp")}</p>

      <Input
        label={t("rules.loverslab.maxItemsPerRun")}
        type="number"
        min={1}
        max={100}
        value={loverslabDraft.maxItemsPerRun ?? ""}
        onChange={(event) => {
          const value = parseIntegerInput(event.target.value, { min: 1, max: 100 });
          if (value !== null) updateLoversLabConfig({ maxItemsPerRun: value });
        }}
      />
      <p className="text-xs text-gray-500">{t("rules.loverslab.maxItemsPerRunHelp")}</p>
      <p className="text-xs text-amber-700">{t("rules.loverslab.rssNotice")}</p>

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.updateDetection")}
        </label>
        <select
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          value={loverslabDraft.updateDetection || "published_time"}
          onChange={(event) =>
            updateLoversLabConfig({ updateDetection: event.target.value as UpdateDetection })
          }
        >
          {updateDetectionOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {t(option.labelKey)}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
};
