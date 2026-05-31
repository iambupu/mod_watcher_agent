import { describe, expect, it } from "vitest";

import { isAdultContent } from "@/utils/modAdult";

describe("isAdultContent", () => {
  it("accepts boolean and string flags", () => {
    expect(isAdultContent(true)).toBe(true);
    expect(isAdultContent(false)).toBe(false);
    expect(isAdultContent("true")).toBe(true);
    expect(isAdultContent("false")).toBe(false);
  });

  it("treats missing or unknown flags as non-adult", () => {
    expect(isAdultContent(undefined)).toBe(false);
    expect(isAdultContent("unknown")).toBe(false);
  });
});
