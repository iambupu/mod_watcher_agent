import React from "react";
import type { ModSource } from "@/types";

interface SourceBadgeProps {
  source: ModSource;
  className?: string;
}

const sourceConfig: Record<ModSource, { label: string; classes: string }> = {
  nexusmods: { label: "Nexus Mods", classes: "bg-blue-100 text-blue-800 border-blue-300" },
  loverslab: { label: "LoversLab", classes: "bg-green-100 text-green-800 border-green-300" },
};

export const SourceBadge: React.FC<SourceBadgeProps> = ({ source, className = "" }) => {
  const config = sourceConfig[source];
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-medium ${config.classes} ${className}`}>
      {config.label}
    </span>
  );
};
