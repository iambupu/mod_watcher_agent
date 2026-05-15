import React from "react";
import { useTranslation } from "react-i18next";
import type { CommonRuleFilters } from "@/types";

interface MetricFilterFieldsProps {
  minDownloads?: number;
  minEndorsements?: number;
  minLikes?: number;
  updatedWithinDays?: number;
  onChange: (patch: Partial<CommonRuleFilters>) => void;
}

export const MetricFilterFields: React.FC<MetricFilterFieldsProps> = ({
  minDownloads,
  minEndorsements,
  minLikes,
  updatedWithinDays,
  onChange,
}) => {
  const { t } = useTranslation();

  const handleNumberChange =
    (key: keyof CommonRuleFilters) =>
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const raw = e.target.value;
      if (raw === "") {
        onChange({ [key]: undefined });
      } else {
        const num = Number(raw);
        if (!isNaN(num) && num >= 0) {
          onChange({ [key]: num });
        }
      }
    };

  return (
    <div className="flex flex-col gap-2">
      <label className="block text-sm font-semibold text-gray-800">
        {t("rules.metrics")}
      </label>
      <div className="grid grid-cols-2 gap-2">
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">
            {t("rules.minDownloads")}
          </label>
          <input
            type="number"
            min={0}
            value={minDownloads ?? ""}
            onChange={handleNumberChange("minDownloads")}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">
            {t("rules.minEndorsements")}
          </label>
          <input
            type="number"
            min={0}
            value={minEndorsements ?? ""}
            onChange={handleNumberChange("minEndorsements")}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">
            {t("rules.minLikes")}
          </label>
          <input
            type="number"
            min={0}
            value={minLikes ?? ""}
            onChange={handleNumberChange("minLikes")}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs font-medium text-gray-600">
            {t("rules.filters.updatedWithinDays")}
          </label>
          <input
            type="number"
            min={0}
            value={updatedWithinDays ?? ""}
            onChange={handleNumberChange("updatedWithinDays")}
            className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm placeholder:text-gray-400 focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
        </div>
      </div>
    </div>
  );
};
