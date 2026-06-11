// 中文注释：提供 json 相关的前端纯函数工具。

export function parseJsonText(value: string, invalidMessage = "Invalid JSON file"): unknown {
  try {
    return JSON.parse(value);
  } catch {
    throw new Error(invalidMessage);
  }
}

export function parseJsonStringArray(value: string | null | undefined): string[] {
  return parseJsonArray(value).filter((item): item is string => typeof item === "string");
}

export function parseJsonArray(value: string | null | undefined): unknown[] {
  if (!value) return [];
  try {
    const parsed = JSON.parse(value);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function parseJsonObject(value: string | null | undefined): Record<string, unknown> {
  if (!value) return {};
  try {
    const parsed = JSON.parse(value);
    return parsed && typeof parsed === "object" && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
  } catch {
    return {};
  }
}
