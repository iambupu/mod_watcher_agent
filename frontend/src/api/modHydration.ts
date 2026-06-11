// 中文注释：封装前端访问后端Mod 摘要补全轮询接口的类型和请求函数。

import type { ModItem } from "@/types";

export function fallbackModItem(
  modId: number,
  {
    url = "",
    firstSeenAt = "",
    lastSeenAt = "",
    translatedSummary,
  }: {
    url?: string;
    firstSeenAt?: string;
    lastSeenAt?: string;
    translatedSummary?: string | null;
  } = {},
): ModItem {
  return {
    id: modId,
    source: "nexusmods",
    external_id: String(modId),
    game: "",
    title: `Mod #${modId}`,
    url,
    tags_json: "[]",
    translated_summary: translatedSummary || undefined,
    ignored: false,
    first_seen_at: firstSeenAt,
    last_seen_at: lastSeenAt,
  };
}

export function mergeTranslatedSummary(mod: ModItem, translatedSummary?: string | null): ModItem {
  const existing = typeof mod.translated_summary === "string" ? mod.translated_summary.trim() : mod.translated_summary;
  const incoming = typeof translatedSummary === "string" ? translatedSummary.trim() : translatedSummary;
  return {
    ...mod,
    translated_summary: existing || incoming || undefined,
  };
}
