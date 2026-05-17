import React from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { AccessMode, LoversLabRuleConfig } from "@/types";

type UpdateDetection = NonNullable<LoversLabRuleConfig["updateDetection"]>;

export const LoversLabRulePanel: React.FC = () => {
  const { t } = useTranslation();
  const loverslabDraft = useRuleEditorStore((s) => s.draft.loverslabDraft);
  const updateLoversLabConfig = useRuleEditorStore((s) => s.updateLoversLabConfig);

  const accessModeOptions: { value: AccessMode; labelKey: string }[] = [
    { value: "rss", labelKey: "rules.loverslab.accessModeRss" },
    { value: "page", labelKey: "rules.loverslab.accessModePage" },
    { value: "both", labelKey: "rules.loverslab.accessModeBoth" },
  ];

  const showFeedUrls = loverslabDraft.accessMode === "rss" || loverslabDraft.accessMode === "both";
  const showPageUrls = loverslabDraft.accessMode === "page" || loverslabDraft.accessMode === "both";

  const updateDetectionOptions: { value: "" | UpdateDetection; labelKey: string }[] = [
    { value: "", labelKey: "rules.loverslab.updateDetection.none" },
    { value: "published_time", labelKey: "rules.loverslab.updateDetection.publishedTime" },
    { value: "updated_time", labelKey: "rules.loverslab.updateDetection.updatedTime" },
    { value: "page_hash", labelKey: "rules.loverslab.updateDetection.pageHash" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <Input
        label={t("rules.loverslab.gameLabel")}
        placeholder={t("rules.loverslab.gameLabelPlaceholder")}
        required
        value={loverslabDraft.gameLabel || ""}
        onChange={(e) => updateLoversLabConfig({ gameLabel: e.target.value })}
      />

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.accessMode")}
        </label>
        <select
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={loverslabDraft.accessMode || ""}
          onChange={(e) => updateLoversLabConfig({ accessMode: e.target.value as AccessMode })}
        >
          <option value="">--</option>
          {accessModeOptions.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
      </div>

      {showFeedUrls && (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">
            {t("rules.loverslab.feedUrls")}
          </label>
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
      )}

      {showPageUrls && (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium text-gray-700">
            {t("rules.loverslab.pageUrls")}
          </label>
          <textarea
            className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            rows={3}
            placeholder={t("rules.loverslab.pageUrlsPlaceholder")}
            value={(loverslabDraft.pageUrls || []).join("\n")}
            onChange={(e) =>
              updateLoversLabConfig({
                pageUrls: e.target.value
                  .split("\n")
                  .map((s) => s.trim())
                  .filter(Boolean),
              })
            }
          />
        </div>
      )}

      <Input
        label={t("rules.loverslab.maxItemsPerRun")}
        type="number"
        value={loverslabDraft.maxItemsPerRun ?? ""}
        onChange={(e) =>
          updateLoversLabConfig({
            maxItemsPerRun: e.target.value === "" ? undefined : Number(e.target.value),
          })
        }
      />

      <div className="flex flex-col gap-1">
        <label className="text-sm font-medium text-gray-700">
          {t("rules.loverslab.updateDetection")}
        </label>
        <select
          className="rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          value={loverslabDraft.updateDetection || ""}
          onChange={(e) =>
            updateLoversLabConfig({
              updateDetection: e.target.value
                ? (e.target.value as UpdateDetection)
                : undefined,
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
