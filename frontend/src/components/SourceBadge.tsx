// 中文注释：提供 SourceBadge 业务组件。

import React from "react";
import type { ModSource } from "@/types";

interface SourceBadgeProps {
  source: ModSource;
  className?: string;
}

const sourceConfig: Record<ModSource, { label: string; classes: string }> = {
  nexusmods: { label: "Nexus Mods", classes: "bg-cyan-50 text-cyan-900 border-cyan-300" },
  loverslab: { label: "LoversLab", classes: "bg-sky-50 text-sky-900 border-sky-300" },
};

export const SourceBadge: React.FC<SourceBadgeProps> = ({ source, className = "" }) => {
  const config = sourceConfig[source];
  return (
    <span className={`inline-flex items-center whitespace-nowrap rounded-md border px-2 py-0.5 text-xs font-medium ${config.classes} ${className}`}>
      {config.label}
    </span>
  );
};
