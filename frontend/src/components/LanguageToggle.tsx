import React from "react";
import { useTranslation } from "react-i18next";
import type { UILanguage } from "@/types";

interface LanguageToggleProps {
  current: UILanguage;
  onChange: (lang: UILanguage) => void;
}

const languages: { value: UILanguage; label: string }[] = [
  { value: "zh-CN", label: "中文" },
  { value: "en-US", label: "English" },
  { value: "ja-JP", label: "日本語" },
];

export const LanguageToggle: React.FC<LanguageToggleProps> = ({ current, onChange }) => {
  const { t } = useTranslation();

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-gray-500">{t("settings.uiLanguage")}:</span>
      <select
        value={current}
        onChange={(e) => onChange(e.target.value as UILanguage)}
        className="rounded-md border border-gray-300 px-2 py-1 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
      >
        {languages.map((lang) => (
          <option key={lang.value} value={lang.value}>
            {lang.label}
          </option>
        ))}
      </select>
    </div>
  );
};
