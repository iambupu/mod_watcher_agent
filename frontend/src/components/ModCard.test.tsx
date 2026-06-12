import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ModCard } from "./ModCard";
import { useUIStore } from "@/stores/uiStore";
import type { ModItem } from "@/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

const longSummary = Array.from({ length: 60 }, (_, index) => `summary-${index}`).join(" ");

function makeMod(overrides: Partial<ModItem> = {}): ModItem {
  return {
    id: 1,
    source: "nexusmods",
    external_id: "1",
    game: "skyrimspecialedition",
    title: "Unofficial Performance Patch",
    url: "https://example.com/mod/1",
    tags_json: "[]",
    original_summary: longSummary,
    ignored: false,
    first_seen_at: "2026-01-01T00:00:00Z",
    last_seen_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

function installResizeObserverMock() {
  const observe = vi.fn();
  const disconnect = vi.fn();
  const resizeObserver = vi.fn(() => ({ observe, disconnect }));
  globalThis.ResizeObserver = resizeObserver as unknown as typeof ResizeObserver;
  return { resizeObserver, observe, disconnect };
}

describe("ModCard", () => {
  beforeEach(() => {
    useUIStore.setState({ summaryMode: "original" });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    Reflect.deleteProperty(globalThis, "ResizeObserver");
  });

  it("observes summary overflow by default", () => {
    const { resizeObserver, observe } = installResizeObserverMock();

    render(<ModCard mod={makeMod()} />);

    expect(resizeObserver).toHaveBeenCalledTimes(1);
    expect(observe).toHaveBeenCalledTimes(1);
  });

  it("can skip summary overflow observers for dense lists", () => {
    const { resizeObserver, observe } = installResizeObserverMock();

    render(
      <>
        <ModCard mod={makeMod({ id: 1 })} measureSummaryOverflow={false} />
        <ModCard mod={makeMod({ id: 2 })} measureSummaryOverflow={false} />
      </>,
    );

    expect(resizeObserver).not.toHaveBeenCalled();
    expect(observe).not.toHaveBeenCalled();
    expect(screen.getAllByRole("button", { name: "mod.expandSummary" })).toHaveLength(2);
  });

  it("still expands text-truncated summaries without overflow measurement", () => {
    installResizeObserverMock();

    render(<ModCard mod={makeMod()} measureSummaryOverflow={false} />);

    expect(screen.queryByText(longSummary)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "mod.expandSummary" }));

    expect(screen.getByText(longSummary)).toBeInTheDocument();
  });

  it("keeps thumbnails out of document flow so image loading cannot resize cards", () => {
    render(<ModCard mod={makeMod({ thumbnail_url: "https://example.com/thumb.png" })} />);

    const image = screen.getByRole("img", { name: "Unofficial Performance Patch" });
    const frame = image.parentElement;

    expect(image).toHaveAttribute("loading", "lazy");
    expect(image).toHaveAttribute("decoding", "async");
    expect(image).toHaveClass("absolute", "inset-0", "h-full", "w-full", "object-cover");
    expect(frame).toHaveClass("overflow-hidden", "aspect-[300/169]");
  });
});
