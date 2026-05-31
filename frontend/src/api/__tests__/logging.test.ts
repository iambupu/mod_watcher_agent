import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchLogs } from "@/api/logging";

describe("logging API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("clamps log limit to backend bounds", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ entries: [] }),
    } as Response);

    await fetchLogs({ limit: 0 });
    await fetchLogs({ limit: 1200 });

    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1][0]));
    expect(firstUrl.searchParams.get("limit")).toBe("1");
    expect(secondUrl.searchParams.get("limit")).toBe("1000");
  });

  it("treats malformed log entry lists as empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => null,
    } as Response);

    await expect(fetchLogs()).resolves.toEqual({ entries: [] });
  });
});
