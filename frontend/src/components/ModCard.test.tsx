import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ModCard } from "@/components/ModCard";
import type { ModItem } from "@/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const baseMod: ModItem = {
  id: 42,
  source: "nexusmods",
  external_id: "fallout4:42",
  game: "Fallout 4",
  title: "Readable Overlay Test",
  url: "https://example.com/mod/42",
  author: "Tester",
  tags_json: "[]",
  original_summary: "A mod with a light thumbnail.",
  thumbnail_url: "https://example.com/light-thumbnail.jpg",
  ignored: false,
  first_seen_at: "2026-07-04T00:00:00Z",
  last_seen_at: "2026-07-04T00:00:00Z",
};

describe("ModCard", () => {
  it("uses a high-contrast image overlay for the game label", () => {
    render(<ModCard mod={baseMod} />);

    const badge = screen.getByTitle("Fallout 4");

    expect(badge).toHaveClass("bg-slate-950/90");
    expect(badge).toHaveClass("text-white");
    expect(badge).toHaveClass("ring-black/35");
    expect(badge.className).toContain("[text-shadow:0_1px_2px_rgba(0,0,0,0.72)]");
  });
});
