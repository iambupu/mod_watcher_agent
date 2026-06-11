// 中文注释：封装前端访问后端listResponse.test接口的类型和请求函数。

import { describe, expect, it } from "vitest";

import { nonNegativeInteger, normalizeListResponse } from "@/api/listResponse";

describe("normalizeListResponse", () => {
  it("keeps valid items and floors non-negative totals", () => {
    expect(normalizeListResponse<number>({ items: [1, 2], total: "2.9" })).toEqual({
      items: [1, 2],
      total: 2,
    });
  });

  it("falls back to empty items and item length totals for malformed payloads", () => {
    expect(normalizeListResponse<number>({ items: { bad: true }, total: "bad" })).toEqual({
      items: [],
      total: 0,
    });
    expect(normalizeListResponse<number>({ items: [1, 2, 3], total: -1 })).toEqual({
      items: [1, 2, 3],
      total: 3,
    });
  });
});

describe("nonNegativeInteger", () => {
  it("normalizes dirty numeric response fields", () => {
    expect(nonNegativeInteger("3.9")).toBe(3);
    expect(nonNegativeInteger(-1, 7)).toBe(7);
    expect(nonNegativeInteger("bad", 7)).toBe(7);
  });
});
