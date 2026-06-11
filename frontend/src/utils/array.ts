// 中文注释：提供 array 相关的前端纯函数工具。

export function arrayOrEmpty<T>(value: unknown): T[] {
  return Array.isArray(value) ? value as T[] : [];
}
