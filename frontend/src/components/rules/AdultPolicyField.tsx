import React from "react";
import { useTranslation } from "react-i18next";
import type { AdultPolicy, CommonRuleFilters } from "@/types";

interface AdultPolicyFieldProps {
  adultPolicy?: AdultPolicy;
  onChange: (patch: Partial<CommonRuleFilters>) => void;
}

const ADULT_POLICY_I18N: Record<AdultPolicy, string> = {
  include: "discover.adultInclude",
  exclude: "discover.adultExclude",
  only: "discover.adultOnly",
};

export const AdultPolicyField: React.FC<AdultPolicyFieldProps> = ({
  adultPolicy,
  onChange,
}) => {
  const { t } = useTranslation();
  const options: AdultPolicy[] = ["include", "exclude", "only"];

  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-semibold text-gray-800">
        {t("rules.adultPolicy")}
      </label>
      <select
        value={adultPolicy ?? "exclude"}
        onChange={(e) =>
          onChange({ adultPolicy: e.target.value as AdultPolicy })
        }
        className="rounded-md border border-gray-300 px-3 py-1.5 text-sm shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        {options.map((opt) => (
          <option key={opt} value={opt}>
            {t(ADULT_POLICY_I18N[opt])}
          </option>
        ))}
      </select>
    </div>
  );
};
