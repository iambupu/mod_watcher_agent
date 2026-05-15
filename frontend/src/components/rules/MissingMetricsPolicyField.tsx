import React from "react";
import { useTranslation } from "react-i18next";
import type { MissingMetricsPolicy, CommonRuleFilters } from "@/types";

interface MissingMetricsPolicyFieldProps {
  missingMetricsPolicy?: MissingMetricsPolicy;
  onChange: (patch: Partial<CommonRuleFilters>) => void;
}

export const MissingMetricsPolicyField: React.FC<
  MissingMetricsPolicyFieldProps
> = ({ missingMetricsPolicy, onChange }) => {
  const { t } = useTranslation();
  const options: MissingMetricsPolicy[] = ["pass", "reject"];

  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-semibold text-gray-800">
        {t("rules.filters.missingMetricsPolicy")}
      </label>
      <select
        value={missingMetricsPolicy ?? "pass"}
        onChange={(e) =>
          onChange({
            missingMetricsPolicy: e.target.value as MissingMetricsPolicy,
          })
        }
        className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {t(`rules.filters.missingMetricsPolicy.${opt}`)}
          </option>
        ))}
      </select>
    </div>
  );
};
