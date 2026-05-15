import React, { useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

const QUERY_MODE_OPTIONS = [
  { value: "", labelKey: "rules.nexusmods.queryModeAll" },
  { value: "updated", labelKey: "rules.nexusmods.queryModeUpdated" },
  { value: "trending", labelKey: "rules.nexusmods.queryModeTrending" },
  { value: "newest", labelKey: "rules.nexusmods.queryModeNewest" },
];

const SORT_BY_OPTIONS = [
  { value: "updated_desc", labelKey: "rules.sortUpdatedDesc" },
  { value: "downloads_desc", labelKey: "rules.sortDownloadsDesc" },
  { value: "endorsements_desc", labelKey: "rules.sortEndorsementsDesc" },
  { value: "first_seen_desc", labelKey: "rules.sortFirstSeenDesc" },
];

function parseTagInput(raw: string): string[] {
  return raw
    .split(/[,，]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function tagsToString(tags?: string[]): string {
  return (tags || []).join(", ");
}

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
        const num = Number(value);
        if (isNaN(num) || num <= 0) {
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
      const value =
        field === "updatedSinceDays" ? Number(raw) : raw;
      const error = validate(field, raw);
      setFieldError(field, error);
      updateNexusConfig({ [field]: value });
    },
    [updateNexusConfig, validate, setFieldError],
  );

  const handleTagsChange = useCallback(
    (field: "categoryNames" | "tags", raw: string) => {
      const parsed = parseTagInput(raw);
      updateNexusConfig({ [field]: parsed });
    },
    [updateNexusConfig],
  );

  const selectClass =
    "rounded-md border border-gray-300 px-3 py-2 text-sm shadow-sm bg-white focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

  return (
    <div className="flex flex-col gap-4">
      <div>
        <label className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.gameDomainName")}
          <span className="text-red-500 ml-0.5">*</span>
        </label>
        <Input
          value={nexusConfig.gameDomainName}
          onChange={(e) => handleChange("gameDomainName", e.target.value)}
          onBlur={(e) => handleBlur("gameDomainName", e.target.value)}
          placeholder={t("rules.nexusmods.gameDomainNamePlaceholder")}
          error={errors.gameDomainName}
        />
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
        />
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="nm-query-mode" className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.queryMode")}
        </label>
        <select
          id="nm-query-mode"
          className={selectClass}
          value={nexusConfig.queryMode || ""}
          onChange={(e) => updateNexusConfig({ queryMode: e.target.value || undefined })}
        >
          {QUERY_MODE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label htmlFor="nm-sort-by" className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.sortBy")}
        </label>
        <select
          id="nm-sort-by"
          className={selectClass}
          value={nexusConfig.sortBy || ""}
          onChange={(e) => updateNexusConfig({ sortBy: e.target.value || undefined })}
        >
          {SORT_BY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {t(opt.labelKey)}
            </option>
          ))}
        </select>
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.categoryNames")}
        </label>
        <Input
          value={tagsToString(nexusConfig.categoryNames)}
          onChange={(e) => handleTagsChange("categoryNames", e.target.value)}
          placeholder={t("rules.nexusmods.categoryNamesPlaceholder")}
        />
      </div>

      <div>
        <label className="text-sm font-medium text-gray-700">
          {t("rules.nexusmods.tags")}
        </label>
        <Input
          value={tagsToString(nexusConfig.tags)}
          onChange={(e) => handleTagsChange("tags", e.target.value)}
          placeholder={t("rules.nexusmods.tagsPlaceholder")}
        />
      </div>
    </div>
  );
};
