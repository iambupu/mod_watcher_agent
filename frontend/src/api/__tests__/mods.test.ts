import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchIgnoredMods, fetchModGames, fetchMods, fetchRecommendedMods } from "@/api/mods";

describe("mods API", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("clamps pagination params to backend bounds", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], total: 0 }),
    } as Response);

    await fetchMods({ offset: -10, limit: 0 });
    await fetchMods({ offset: 0, limit: 999 });

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1][0]));
    expect(url.searchParams.get("offset")).toBe("0");
    expect(url.searchParams.get("limit")).toBe("1");
    expect(secondUrl.searchParams.get("limit")).toBe("200");
  });

  it("clamps recommendation limit to backend bounds", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], total: 0 }),
    } as Response);

    await fetchRecommendedMods(0);
    await fetchRecommendedMods(99);

    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1][0]));
    expect(firstUrl.searchParams.get("limit")).toBe("1");
    expect(secondUrl.searchParams.get("limit")).toBe("20");
  });

  it("normalizes malformed mod list responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: undefined, total: "bad" }),
    } as Response);

    await expect(fetchMods({})).resolves.toEqual({ items: [], total: 0 });
    await expect(fetchIgnoredMods({})).resolves.toEqual({ items: [], total: 0 });
  });

  it("treats malformed game option responses as empty", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [] }),
    } as Response);

    await expect(fetchModGames()).resolves.toEqual([]);
  });
});
