import { describe, expect, it } from "vitest";

import { positiveIntegerIds } from "./ids";

describe("positiveIntegerIds", () => {
  it("keeps only positive integer numbers", () => {
    expect(positiveIntegerIds([1, 0, -1, 2.5, Number.NaN, "3", 4])).toEqual([1, 4]);
  });

  it("returns empty for non-arrays", () => {
    expect(positiveIntegerIds(undefined)).toEqual([]);
    expect(positiveIntegerIds({ ids: [1] })).toEqual([]);
  });
});
