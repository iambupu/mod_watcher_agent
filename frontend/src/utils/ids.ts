// 中文注释：提供 ids 相关的前端纯函数工具。

export function positiveIntegerIds(values: unknown): number[] {
  if (!Array.isArray(values)) return [];
  return values.filter((value): value is number => (
    typeof value === "number"
    && Number.isInteger(value)
    && value > 0
  ));
}
