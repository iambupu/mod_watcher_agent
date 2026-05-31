import { describe, expect, it, vi } from "vitest";

import { formatLocalDateTime } from "./time";

describe("formatLocalDateTime", () => {
  it("uses the fallback for empty values", () => {
    expect(formatLocalDateTime(undefined)).toBe("-");
    expect(formatLocalDateTime(null, "never")).toBe("never");
  });

  it("formats ISO-like values with either T or space separators", () => {
    vi.spyOn(Date.prototype, "toLocaleString").mockReturnValue("formatted");

    expect(formatLocalDateTime("2026-05-30T12:34:56")).toBe("formatted");
    expect(formatLocalDateTime("2026-05-30 12:34:56")).toBe("formatted");
  });

  it("returns invalid values unchanged", () => {
    expect(formatLocalDateTime("not a date")).toBe("not a date");
  });
});
