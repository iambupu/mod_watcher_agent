// 中文注释：提供规则编辑器里的 NexusModsRulePanel 表单组件。

import React, { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { TokenInput } from "@/components/rules/TokenInput";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { NexusModsRuleConfig } from "@/types";
import { parseIntegerInput } from "@/utils/numberInput";

type NexusQueryMode = NonNullable<NexusModsRuleConfig["queryMode"]>;
type NexusSortBy = NonNullable<NexusModsRuleConfig["sortBy"]>;

const QUERY_MODE_OPTIONS: { value: "" | NexusQueryMode; labelKey: string }[] = [
  { value: "", labelKey: "rules.nexusmods.queryModeAll" },
  { value: "updated", labelKey: "rules.nexusmods.queryModeUpdated" },
  { value: "created", labelKey: "rules.nexusmods.queryModeCreated" },
];

const SORT_BY_OPTIONS: { value: NexusSortBy; labelKey: string }[] = [
  { value: "updatedAt_desc", labelKey: "rules.sortUpdatedDesc" },
  { value: "createdAt_desc", labelKey: "rules.sortCreatedDesc" },
  { value: "downloads_desc", labelKey: "rules.sortDownloadsDesc" },
  { value: "endorsements_desc", labelKey: "rules.sortEndorsementsDesc" },
];

export const NexusModsRulePanel: React.FC = () => {
  const { t } = useTranslation();
  const nexusConfig = useRuleEditorStore((s) => s.draft.nexusmodsDraft);
  const updateNexusConfig = useRuleEditorStore((s) => s.updateNexusConfig);

  const [errors, setErrors] = useState<Record<string, string>>({});

  const validate = useCallback(
    (field: string, value: unknown): string => {
      if (field === "gameDomainName" && (!value || (value as string).trim() === "")) {
        return t("rules.nexusmods.errors.gameDomainNameRequired");
      }
      if (field === "updatedSinceDays") {
        if (parseIntegerInput(String(value), { min: 1, max: 365 }) == null) {
          return t("rules.nexusmods.errors.updatedSinceDaysNumeric");
        }
      }
      return "";
    },
    [t],
  );

  const setFieldError = useCallback(
    (field: string, error: string) => {
      setErrors((prev) => {
        const next = { ...prev };
        if (error) {
          next[field] = error;
        } else {
          delete next[field];
        }
        return next;
      });
    },
    [],
  );

  const handleBlur = useCallback(
    (field: keyof typeof nexusConfig, raw: string) => {
      const error = validate(field, raw);
      setFieldError(field, error);
    },
    [validate, setFieldError],
  );

  const handleChange = useCallback(
    (field: keyof typeof nexusConfig, raw: string) => {
      const error = validate(field, raw);
      setFieldError(field, error);
      if (field === "updatedSinceDays") {
        const value = parseIntegerInput(raw, { min: 1, max: 365 });
        if (value != null) {
          updateNexusConfig({ updatedSinceDays: value });
        }
        return;
      }
      const value = raw;
      updateNexusConfig({ [field]: value });
    },
    [updateNexusConfig, validate, setFieldError],
  );

  const selectClass =
    "h-10 rounded-lg border border-slate-300 px-3 py-2 text-sm shadow-sm bg-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <div>
        <label className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.gameDomainName")}
          <span className="text-red-500 ml-0.5">*</span>
        </label>
        <Input
          label=""
          value={nexusConfig.gameDomainName}
          onChange={(e) => handleChange("gameDomainName", e.target.value)}
          onBlur={(e) => handleBlur("gameDomainName", e.target.value)}
          placeholder={t("rules.nexusmods.gameDomainNamePlaceholder")}
          error={errors.gameDomainName}
          className="h-10 rounded-lg border-slate-300"
        />
        <p className="mt-1 text-xs leading-5 text-gray-500">
          {t("rules.nexusmods.gameDomainNameHelp")}
        </p>
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.updatedSinceDays")}
          <span className="text-red-500 ml-0.5">*</span>
        </label>
        <Input
          type="number"
          value={nexusConfig.updatedSinceDays}
          onChange={(e) => handleChange("updatedSinceDays", e.target.value)}
          onBlur={(e) => handleBlur("updatedSinceDays", e.target.value)}
          placeholder={t("rules.nexusmods.updatedSinceDaysPlaceholder") || "7"}
          error={errors.updatedSinceDays}
          className="h-10 rounded-lg border-slate-300"
        />
        <p className="mt-1 text-xs leading-5 text-gray-500">
          {t("rules.nexusmods.updatedSinceDaysHelp")}
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="nm-query-mode" className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.queryMode")}
        </label>
        <select
          id="nm-query-mode"
          className={selectClass}
          value={nexusConfig.queryMode || ""}
          onChange={(e) =>
            updateNexusConfig({
              queryMode: e.target.value
                ? (e.target.value as NexusQueryMode)
                : undefined,
            })
          }
        >
          {QUERY_MODE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
        <p className="text-xs leading-5 text-gray-500">
          {t("rules.nexusmods.queryModeHelp")}
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="nm-sort-by" className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.sortBy")}
        </label>
        <select
          id="nm-sort-by"
          className={selectClass}
          value={nexusConfig.sortBy || ""}
          onChange={(e) =>
            updateNexusConfig({
              sortBy: e.target.value
                ? (e.target.value as NexusSortBy)
                : undefined,
            })
          }
        >
          {SORT_BY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
        <p className="text-xs leading-5 text-gray-500">
          {t("rules.nexusmods.sortByHelp")}
        </p>
      </div>

      <TokenInput
        label={t("rules.nexusmods.categoryNames")}
        description={t("rules.nexusmods.categoryNamesHelp")}
        placeholder={t("rules.nexusmods.categoryNamesPlaceholder")}
        values={nexusConfig.categoryNames}
        onChange={(categoryNames) => updateNexusConfig({ categoryNames })}
      />

      <TokenInput
        label={t("rules.nexusmods.tags")}
        description={t("rules.nexusmods.tagsHelp")}
        placeholder={t("rules.nexusmods.tagsPlaceholder")}
        values={nexusConfig.tags}
        onChange={(tags) => updateNexusConfig({ tags })}
      />
    </div>
  );
};
