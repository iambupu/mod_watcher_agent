import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchUpdates, hydrateUpdateEvent, markAllUpdatesSeen } from "@/api/updates";

describe("updates api", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("serializes list filters as query strings", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], total: 0 }),
    } as Response);

    await fetchUpdates({
      favorite_id: 42,
      seen: false,
      offset: 10,
      limit: 25,
    });

    const url = new URL(String(fetchMock.mock.calls[0][0]));
    expect(url.pathname).toBe("/api/updates");
    expect(url.searchParams.get("favorite_id")).toBe("42");
    expect(url.searchParams.get("seen")).toBe("false");
    expect(url.searchParams.get("offset")).toBe("10");
    expect(url.searchParams.get("limit")).toBe("25");
  });

  it("clamps pagination params to backend bounds", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], total: 0 }),
    } as Response);

    await fetchUpdates({ offset: -10, limit: 0 });
    await fetchUpdates({ offset: 3.8, limit: 999 });

    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1][0]));
    expect(firstUrl.searchParams.get("offset")).toBe("0");
    expect(firstUrl.searchParams.get("limit")).toBe("1");
    expect(secondUrl.searchParams.get("offset")).toBe("3");
    expect(secondUrl.searchParams.get("limit")).toBe("200");
  });

  it("omits invalid favorite id filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: [], total: 0 }),
    } as Response);

    await fetchUpdates({ favorite_id: Number.NaN });
    await fetchUpdates({ favorite_id: -1 });

    const firstUrl = new URL(String(fetchMock.mock.calls[0][0]));
    const secondUrl = new URL(String(fetchMock.mock.calls[1][0]));
    expect(firstUrl.searchParams.has("favorite_id")).toBe(false);
    expect(secondUrl.searchParams.has("favorite_id")).toBe(false);
  });

  it("normalizes malformed update list responses", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ items: undefined, total: "bad" }),
    } as Response);

    await expect(fetchUpdates()).resolves.toEqual({ items: [], total: 0 });
  });

  it("normalizes mark-all update counts", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => null,
    } as Response);

    await expect(markAllUpdatesSeen()).resolves.toEqual({ updated: 0 });
  });

  it("normalizes boolean-like seen values from backend payloads", () => {
    expect(
      hydrateUpdateEvent({
        id: 1,
        mod_id: 10,
        detected_at: "2026-01-01T00:00:00Z",
        seen: "false",
      }).seen,
    ).toBe(false);
  });

  it("merges top-level translated summary into embedded mod payloads", () => {
    const event = hydrateUpdateEvent({
      id: 1,
      mod_id: 10,
      detected_at: "2026-01-01T00:00:00Z",
      seen: false,
      translated_summary: "顶层翻译摘要",
      mod: {
        id: 10,
        source: "nexusmods",
        external_id: "10",
        game: "Skyrim",
        title: "Test Mod",
        url: "https://example.com/mod",
        tags_json: "[]",
        ignored: false,
        first_seen_at: "2026-01-01T00:00:00Z",
        last_seen_at: "2026-01-01T00:00:00Z",
      },
    });

    expect(event.mod.translated_summary).toBe("顶层翻译摘要");
  });

  it("uses top-level translated summary when embedded mod summary is blank", () => {
    const event = hydrateUpdateEvent({
      id: 1,
      mod_id: 10,
      favorite_id: null,
      old_version: null,
      new_version: null,
      old_updated_at: null,
      new_updated_at: null,
      change_summary: "",
      detected_at: "2026-01-01T00:00:00Z",
      seen: false,
      translated_summary: "顶层翻译摘要",
      mod: {
        id: 10,
        source: "nexusmods",
        external_id: "10",
        game: "Skyrim",
        title: "Test Mod",
        url: "https://example.com/mod",
        tags_json: "[]",
        ignored: false,
        first_seen_at: "2026-01-01T00:00:00Z",
        last_seen_at: "2026-01-01T00:00:00Z",
        translated_summary: "",
      },
    });

    expect(event.mod.translated_summary).toBe("顶层翻译摘要");
  });
});
