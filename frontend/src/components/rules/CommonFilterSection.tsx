import React from "react";
import { useTranslation } from "react-i18next";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { CommonRuleFilters } from "@/types";
import { KeywordFilterEditor } from "./KeywordFilterEditor";
import { MetricFilterFields } from "./MetricFilterFields";
import { AdultPolicyField } from "./AdultPolicyField";
import { MissingMetricsPolicyField } from "./MissingMetricsPolicyField";
import { LlmFilterSection } from "./LlmFilterSection";

export const CommonFilterSection: React.FC = () => {
  const { t } = useTranslation();
  const commonFilters = useRuleEditorStore((s) => s.draft.commonFilters);
  const updateCommonFilter = useRuleEditorStore((s) => s.updateCommonFilter);

  const handleChange = (patch: Partial<CommonRuleFilters>) => {
    updateCommonFilter(patch);
  };

  const includeKeywords = commonFilters.includeKeywords ?? [];
  const excludeKeywords = commonFilters.excludeKeywords ?? [];

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-gray-200 p-4">
      <h3 className="text-base font-semibold text-gray-900">{t("rules.filters.commonFilters")}</h3>
      <KeywordFilterEditor
        includeKeywords={includeKeywords}
        excludeKeywords={excludeKeywords}
        onChange={handleChange}
      />
      <MetricFilterFields
        minDownloads={commonFilters.minDownloads}
        minEndorsements={commonFilters.minEndorsements}
        minLikes={commonFilters.minLikes}
        updatedWithinDays={commonFilters.updatedWithinDays}
        onChange={handleChange}
      />
      <AdultPolicyField
        adultPolicy={commonFilters.adultPolicy}
        onChange={handleChange}
      />
      <MissingMetricsPolicyField
        missingMetricsPolicy={commonFilters.missingMetricsPolicy}
        onChange={handleChange}
      />
      <LlmFilterSection
        llmFilter={commonFilters.llmFilter}
        onChange={handleChange}
      />
    </div>
  );
};
