import React from "react";
import { useTranslation } from "react-i18next";
import type { LlmFilterConfig, LlmFilterMode, CommonRuleFilters } from "@/types";

interface LlmFilterSectionProps {
  llmFilter?: LlmFilterConfig;
  onChange: (patch: Partial<CommonRuleFilters>) => void;
}

export const LlmFilterSection: React.FC<LlmFilterSectionProps> = ({
  llmFilter,
  onChange,
}) => {
  const { t } = useTranslation();
  const enabled = llmFilter?.enabled ?? false;
  const prompt = llmFilter?.prompt ?? "";
  const mode = llmFilter?.mode ?? "assist_only";
  const minConfidence = llmFilter?.minConfidence ?? 0.5;

  const handleToggleEnabled = () => {
    onChange({
      llmFilter: {
        enabled: !enabled,
        prompt,
        mode,
        minConfidence,
      },
    });
  };

  const handlePromptChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    onChange({
      llmFilter: { enabled, prompt: e.target.value, mode, minConfidence },
    });
  };

  const handleModeChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    onChange({
      llmFilter: {
        enabled,
        prompt,
        mode: e.target.value as LlmFilterMode,
        minConfidence,
      },
    });
  };

  const handleConfidenceChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange({
      llmFilter: {
        enabled,
        prompt,
        mode,
        minConfidence: Number(e.target.value),
      },
    });
  };

  const confidencePercent = Math.round(minConfidence * 100);

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-3">
      <div className="flex items-center justify-between">
        <label className="text-sm text-gray-700">
          {t("rules.filters.llmFilterEnabled")}
        </label>
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={handleToggleEnabled}
          className={`relative inline-flex h-5 w-9 shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors ${
            enabled ? "bg-blue-600" : "bg-gray-300"
          }`}
        >
          <span
            className={`pointer-events-none block h-4 w-4 rounded-full bg-white shadow transform transition-transform ${
              enabled ? "translate-x-4" : "translate-x-0"
            }`}
          />
        </button>
      </div>
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-600">
          {t("rules.filters.llmPrompt")}
        </label>
        <textarea
          value={prompt}
          onChange={handlePromptChange}
          disabled={!enabled}
          placeholder={t("rules.filters.llmPromptPlaceholder")}
          rows={3}
          className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100"
        />
      </div>
      <div className="grid gap-3 md:grid-cols-[1fr_220px]">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">
            {t("rules.filters.llmMode")}
          </label>
          <select
            value={mode}
            onChange={handleModeChange}
            disabled={!enabled}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500 disabled:bg-gray-100"
          >
            <option value="assist_only">
              {t("rules.filters.llmMode.assistOnly")}
            </option>
            <option value="must_pass">
              {t("rules.filters.llmMode.mustPass")}
            </option>
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">
            {t("rules.filters.llmConfidence")} ({confidencePercent}%)
          </label>
          <input
            type="range"
            min={0}
            max={1}
            step={0.05}
            value={minConfidence}
            onChange={handleConfidenceChange}
            disabled={!enabled}
            className="h-9 w-full"
          />
        </div>
      </div>
    </div>
  );
};
