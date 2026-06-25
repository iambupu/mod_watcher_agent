// 中文注释：把来源站点的英文分类值转换为前端可翻译的显示标签。

import type { TFunction } from "i18next";

export function modCategoryTranslationKey(category: string | null | undefined): string {
  const normalized = String(category || "")
    .trim()
    .replace(/&amp;/gi, "&")
    .replace(/['’]/g, "")
    .toLowerCase()
    .replace(/&/g, " and ")
    .replace(/[^a-z0-9]+/g, ".")
    .replace(/^\.+|\.+$/g, "")
    .replace(/\.+/g, ".");
  return normalized ? `modCategory.${normalized}` : "";
}

export function formatModCategory(
  category: string | null | undefined,
  t: TFunction,
): string {
  const fallback = String(category || "").trim();
  if (!fallback) return "";
  const key = modCategoryTranslationKey(fallback);
  return key ? t(key, { defaultValue: fallback }) : fallback;
}
