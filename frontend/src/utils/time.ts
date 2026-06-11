// 中文注释：提供 time 相关的前端纯函数工具。

export function formatLocalDateTime(value: string | null | undefined, fallback = "-"): string {
  if (!value) return fallback;
  const normalized = value.includes("T") ? value : value.replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString();
}
