// 中文注释：提供规则编辑器里的 SourceTabs 表单组件。

import React from "react";
import { useTranslation } from "react-i18next";
import { Heart, ShieldCheck } from "lucide-react";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { ModSource } from "@/types";

const sources: ModSource[] = ["nexusmods", "loverslab"];

export const SourceTabs: React.FC = () => {
  const { t } = useTranslation();
  const activeSource = useRuleEditorStore((s) => s.activeSource);
  const switchSource = useRuleEditorStore((s) => s.switchSource);

  return (
    <div className="grid grid-cols-2 overflow-hidden rounded-lg border border-slate-200 bg-slate-100 p-1" role="tablist">
      {sources.map((source) => {
        const isActive = activeSource === source;
        return (
          <button
            key={source}
            role="tab"
            aria-selected={isActive}
            onClick={() => switchSource(source)}
            className={`flex items-center justify-center gap-2 rounded-md px-4 py-2.5 text-sm font-bold transition-all focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-inset ${
              isActive
                ? "bg-blue-600 text-white shadow-sm"
                : "text-slate-600 hover:bg-white hover:text-slate-900"
            }`}
          >
            {source === "nexusmods" ? <ShieldCheck size={16} /> : <Heart size={16} />}
            {t(`rules.sourceTabs.${source}`)}
          </button>
        );
      })}
    </div>
  );
};
