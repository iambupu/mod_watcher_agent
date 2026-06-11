// 中文注释：提供 modTitle 相关的前端纯函数工具。

import type { SummaryMode } from "@/types";

export function formatModTitle(
  mod: { title?: string | null; translated_title_zh?: string | null },
  mode: SummaryMode,
): string {
  const originalTitle = (mod.title || "").trim();
  const translatedTitle = (mod.translated_title_zh || "").trim();

  if (mode === "translated") {
    return translatedTitle || originalTitle;
  }
  if (mode === "bilingual" && translatedTitle && translatedTitle !== originalTitle) {
    return `${translatedTitle}\n${originalTitle}`;
  }
  return originalTitle || translatedTitle;
}
