// 中文注释：提供 modAdult 相关的前端纯函数工具。

import { parseBoolean } from "@/utils/boolean";

export function isAdultContent(value: unknown): boolean {
  return parseBoolean(value, false);
}
