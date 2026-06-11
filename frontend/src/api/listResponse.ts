// 中文注释：封装前端访问后端分页列表响应接口的类型和请求函数。

import { arrayOrEmpty } from "@/utils/array";
import { nonNegativeNumberValue } from "@/utils/numberInput";

export interface NormalizedListResponse<T> {
  items: T[];
  total: number;
}

export function normalizeListResponse<T>(
  data: { items?: unknown; total?: unknown } | null | undefined,
): NormalizedListResponse<T> {
  const items = arrayOrEmpty<T>(data?.items);
  const total = nonNegativeInteger(data?.total, items.length);
  return {
    items,
    total,
  };
}

export function nonNegativeInteger(value: unknown, fallback = 0): number {
  const parsed = nonNegativeNumberValue(value);
  return parsed === null ? fallback : Math.floor(parsed);
}
