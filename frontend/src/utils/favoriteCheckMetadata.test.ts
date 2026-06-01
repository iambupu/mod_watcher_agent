import { describe, expect, it } from "vitest";

import { parseFavoriteCheckEntries } from "./favoriteCheckMetadata";

describe("parseFavoriteCheckEntries", () => {
  it("normalizes boolean-like flags from job metadata", () => {
    const entries = parseFavoriteCheckEntries(JSON.stringify({
      results: {
        favorites: [
          {
            favorite_id: "42",
            title: "Updated Mod",
            update_detected: "false",
            notification_sent: "1",
            last_checked_at: "2026-05-30T00:00:00Z",
          },
        ],
      },
    }));

    expect(entries).toEqual([
      {
        favorite_id: 42,
        title: "Updated Mod",
        update_detected: false,
        notification_sent: true,
        last_checked_at: "2026-05-30T00:00:00Z",
        error: null,
      },
    ]);
  });

  it("drops malformed entries and invalid ids", () => {
    const entries = parseFavoriteCheckEntries(JSON.stringify({
      results: {
        favorites: [
          null,
          { favorite_id: "0", update_detected: true },
          { favorite_id: 7, update_detected: "yes", notification_sent: "no", error: "boom" },
        ],
      },
    }));

    expect(entries).toEqual([
      {
        favorite_id: 7,
        title: null,
        update_detected: true,
        notification_sent: false,
        last_checked_at: null,
        error: "boom",
      },
    ]);
  });
});
