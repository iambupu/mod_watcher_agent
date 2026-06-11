// 中文注释：提供 modSummary 相关的前端纯函数工具。

import type { SummaryMode } from "@/types";

function truncate(text: string, maxLen?: number): string {
  if (!maxLen || text.length <= maxLen) return text;
  return text.slice(0, maxLen).trimEnd() + "...";
}

export function formatModSummary({
  original,
  translated,
  mode,
  maxLength,
  emptyText = "",
}: {
  original?: string | null;
  translated?: string | null;
  mode: SummaryMode;
  maxLength?: number;
  emptyText?: string;
}): string {
  const originalText = truncate((original || "").trim(), maxLength);
  const translatedText = truncate((translated || "").trim(), maxLength);

  if (mode === "translated") {
    return translatedText || originalText || emptyText;
  }
  if (mode === "bilingual") {
    if (translatedText && originalText) {
      return `${translatedText}\n——\n${originalText}`;
    }
    return translatedText || originalText || emptyText;
  }
  return originalText || emptyText;
}
