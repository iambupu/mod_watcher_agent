import React from "react";
import { useTranslation } from "react-i18next";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { ModSource } from "@/types";

const sources: ModSource[] = ["nexusmods", "loverslab"];

export const SourceTabs: React.FC = () => {
  const { t } = useTranslation();
  const activeSource = useRuleEditorStore((s) => s.activeSource);
  const switchSource = useRuleEditorStore((s) => s.switchSource);

  return (
    <div className="flex rounded-md overflow-hidden border border-gray-300" role="tablist">
      {sources.map((source) => {
        const isActive = activeSource === source;
        return (
          <button
            key={source}
            role="tab"
            aria-selected={isActive}
            onClick={() => switchSource(source)}
            className={`flex-1 px-4 py-2 text-sm font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset ${
              isActive
                ? "bg-blue-600 text-white"
                : "bg-gray-100 text-gray-600 hover:bg-gray-200"
            }`}
          >
            {t(`rules.sourceTabs.${source}`)}
          </button>
        );
      })}
    </div>
  );
};
