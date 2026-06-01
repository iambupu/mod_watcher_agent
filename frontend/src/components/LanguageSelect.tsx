import React from "react";
import type { UILanguage } from "@/types";

interface LanguageSelectProps {
  value: UILanguage;
  onChange: (value: UILanguage) => void;
  className?: string;
}

const LANGUAGE_OPTIONS: Array<{ value: UILanguage; label: string }> = [
  { value: "zh-CN", label: "中文" },
  { value: "en-US", label: "English" },
  { value: "ja-JP", label: "日本語" },
];

export const LanguageSelect: React.FC<LanguageSelectProps> = ({
  value,
  onChange,
  className = "h-9 w-full rounded-md border border-gray-300 px-3 text-sm",
}) => {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as UILanguage)}
      className={className}
    >
      {LANGUAGE_OPTIONS.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
};
