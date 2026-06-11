// 中文注释：提供 jobMetadata 相关的前端纯函数工具。

import { parseJsonObject } from "./json";
import { parseWholeIntegerInput } from "./numberInput";

export function parseJobMetadata(metadataJson?: string | null): Record<string, unknown> {
  return parseJsonObject(metadataJson);
}

export function metadataRuleId(metadata: Record<string, unknown>): number {
  const raw = metadata.rule_id;
  const value = typeof raw === "number" || typeof raw === "string"
    ? parseWholeIntegerInput(String(raw), { min: 1 })
    : null;
  return typeof value === "number" ? value : 0;
}
