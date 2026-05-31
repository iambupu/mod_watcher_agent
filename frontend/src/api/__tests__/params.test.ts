import { describe, expect, it } from "vitest";

import { boundedIntegerParam, positiveIntegerParam } from "@/api/params";

describe("boundedIntegerParam", () => {
  it("floors and clamps finite numbers", () => {
    expect(boundedIntegerParam(3.9, { min: 0 })).toBe("3");
    expect(boundedIntegerParam(-2, { min: 0 })).toBe("0");
    expect(boundedIntegerParam(999, { min: 1, max: 200 })).toBe("200");
  });

  it("falls back to the minimum for non-finite values", () => {
    expect(boundedIntegerParam(Number.NaN, { min: 1, max: 200 })).toBe("1");
    expect(boundedIntegerParam(Number.POSITIVE_INFINITY, { min: 1, max: 200 })).toBe("1");
  });
});

describe("positiveIntegerParam", () => {
  it("serializes only positive integers", () => {
    expect(positiveIntegerParam(42)).toBe("42");
    expect(positiveIntegerParam(0)).toBeUndefined();
    expect(positiveIntegerParam(-1)).toBeUndefined();
    expect(positiveIntegerParam(1.5)).toBeUndefined();
    expect(positiveIntegerParam(Number.NaN)).toBeUndefined();
  });
});
