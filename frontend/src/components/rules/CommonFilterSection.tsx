// 中文注释：提供规则编辑器里的 CommonFilterSection 表单组件。

import React from "react";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { CommonRuleFilters } from "@/types";
import { KeywordFilterEditor } from "./KeywordFilterEditor";
import { MetricFilterFields } from "./MetricFilterFields";
import { AdultPolicyField } from "./AdultPolicyField";
import { MissingMetricsPolicyField } from "./MissingMetricsPolicyField";

export const CommonFilterSection: React.FC = () => {
  const commonFilters = useRuleEditorStore((s) => s.draft.commonFilters);
  const updateCommonFilter = useRuleEditorStore((s) => s.updateCommonFilter);

  const handleChange = (patch: Partial<CommonRuleFilters>) => {
    updateCommonFilter(patch);
  };

  const includeKeywords = commonFilters.includeKeywords ?? [];
  const excludeKeywords = commonFilters.excludeKeywords ?? [];

  return (
    <div className="flex flex-col gap-4">
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
    </div>
  );
};
