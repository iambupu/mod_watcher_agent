import { beforeEach, describe, expect, it, vi } from "vitest";

import { get, post } from "@/api/client";
import { checkUpdate, favoriteByModId, favoriteIdByModId, fetchFavoriteRefs, fetchFavorites } from "@/api/favorites";
import type { Favorite } from "@/types";

vi.mock("@/api/client", () => ({
  get: vi.fn(),
  post: vi.fn(),
  put: vi.fn(),
  del: vi.fn(),
}));

describe("favorites API", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes boolean-like favorite fields from backend payloads", async () => {
    vi.mocked(get).mockResolvedValue([
      {
        id: 1,
        mod_id: 10,
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
        tracking_enabled: "false",
        notify_on_update: "1",
        user_tags_json: "[]",
      },
    ]);

    await expect(fetchFavorites()).resolves.toMatchObject([
      {
        trackingEnabled: false,
        notifyOnUpdate: true,
      },
    ]);
  });

  it("normalizes boolean-like favorite update check fields", async () => {
    vi.mocked(post).mockResolvedValue({
      favorite_id: 1,
      mod_id: 10,
      update_detected: "false",
      update_event: null,
      notification_sent: "true",
    });

    await expect(checkUpdate(1)).resolves.toMatchObject({
      updateDetected: false,
      notificationSent: true,
    });
  });

  it("keeps translated summary when fallback mod hydration is used", async () => {
    vi.mocked(get)
      .mockResolvedValueOnce([
        {
          id: 1,
          mod_id: 10,
          tracking_enabled: true,
          notify_on_update: false,
          user_tags_json: "[]",
          translated_summary: "已翻译摘要",
        },
      ])
      .mockRejectedValueOnce(new Error("mod fetch failed"));

    await expect(fetchFavorites()).resolves.toMatchObject([
      {
        mod: {
          translated_summary: "已翻译摘要",
        },
      },
    ]);
  });

  it("treats malformed favorite list responses as empty", async () => {
    vi.mocked(get).mockResolvedValue({ items: [] });

    await expect(fetchFavorites()).resolves.toEqual([]);
  });

  it("fetches lightweight favorite refs without hydrating mods", async () => {
    vi.mocked(get).mockResolvedValue([
      {
        id: 1,
        mod_id: 10,
        tracking_enabled: true,
        notify_on_update: true,
        user_tags_json: "[]",
      },
    ]);

    await expect(fetchFavoriteRefs()).resolves.toEqual([{ id: 1, modId: 10 }]);
    expect(get).toHaveBeenCalledWith("/favorites", { detail: "refs" });
  });

  it("builds favorite lookup maps from canonical mod ids", () => {
    const favorites = [
      {
        id: 1,
        modId: 10,
        mod: { id: 10, title: "One" },
      },
      {
        id: 2,
        modId: 20,
        mod: { id: 99, title: "Stale embedded id" },
      },
    ] as Favorite[];

    expect(favoriteByModId(favorites).get(20)?.id).toBe(2);
    expect(favoriteIdByModId(favorites).get(10)).toBe(1);
  });
});
