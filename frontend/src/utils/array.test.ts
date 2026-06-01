import { describe, expect, it } from "vitest";

import { arrayOrEmpty } from "./array";

describe("arrayOrEmpty", () => {
  it("returns arrays unchanged", () => {
    const items = [1, 2, 3];

    expect(arrayOrEmpty<number>(items)).toBe(items);
  });

  it("returns an empty array for non-arrays", () => {
    expect(arrayOrEmpty(undefined)).toEqual([]);
    expect(arrayOrEmpty({ items: [] })).toEqual([]);
    expect(arrayOrEmpty("not an array")).toEqual([]);
  });
});
