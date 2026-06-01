import { describe, expect, it } from "vitest";

import { parseBoolean } from "@/utils/boolean";

describe("parseBoolean", () => {
  it("parses common boolean-like values", () => {
    expect(parseBoolean(true)).toBe(true);
    expect(parseBoolean(false)).toBe(false);
    expect(parseBoolean("true")).toBe(true);
    expect(parseBoolean("false")).toBe(false);
    expect(parseBoolean("1")).toBe(true);
    expect(parseBoolean("0")).toBe(false);
    expect(parseBoolean(1)).toBe(true);
    expect(parseBoolean(0)).toBe(false);
  });

  it("uses fallback for unknown values", () => {
    expect(parseBoolean("maybe")).toBe(false);
    expect(parseBoolean("maybe", true)).toBe(true);
  });
});
