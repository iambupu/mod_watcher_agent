import { describe, it, expect, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoversLabRulePanel } from "./LoversLabRulePanel";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

describe("LoversLabRulePanel", () => {
  beforeEach(() => {
    useRuleEditorStore.setState({
      draft: {
        name: "",
        enabled: true,
        intervalMinutes: 360,
        commonFilters: {},
        nexusmodsDraft: {
          gameDomainName: "",
          updatedSinceDays: 7,
        },
        loverslabDraft: {
          gameLabel: "",
          accessMode: "rss",
          feedUrls: [],
          pageUrls: [],
          updatedSinceDays: 30,
          maxItemsPerRun: 50,
          updateDetection: "published_time",
        },
        notification: {
          enabled: true,
          mode: "instant",
        },
      },
      activeSource: "loverslab",
      isDirty: false,
      editingRuleId: null,
    });
  });

  it("renders_game_label", () => {
    render(<LoversLabRulePanel />);

    const input = screen.getByPlaceholderText("rules.loverslab.gameLabelPlaceholder");
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue("");

    const label = screen.getByText("rules.loverslab.gameLabel");
    expect(label).toBeInTheDocument();
  });

  it("default_mode_shows_feed", () => {
    render(<LoversLabRulePanel />);
    expect(screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).toBeInTheDocument();
    expect(screen.getByText("rules.loverslab.ruleGuideTitle")).toBeInTheDocument();
    expect(screen.getByText("rules.loverslab.ruleGuideLine1")).toBeInTheDocument();
    expect(screen.getByText("rules.loverslab.ruleGuideLine4")).toBeInTheDocument();
    expect(screen.getByText("rules.loverslab.ruleGuideLine5")).toBeInTheDocument();
  });

  it("does_not_render_page_urls_entry", () => {
    render(<LoversLabRulePanel />);
    expect(screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("rules.loverslab.pageUrlsPlaceholder")).not.toBeInTheDocument();
  });

  it("updates_feed_urls", async () => {
    const user = userEvent.setup();
    render(<LoversLabRulePanel />);
    const textarea = screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder");
    await user.type(textarea, "https://example.com/feed1");
    expect(textarea).toHaveValue("https://example.com/feed1");
  });

  it("normalizes_legacy_page_mode_to_rss", async () => {
    useRuleEditorStore.setState({
      draft: {
        ...useRuleEditorStore.getState().draft,
        loverslabDraft: {
          gameLabel: "skyrim",
          accessMode: "both",
          feedUrls: ["https://example.com/feed1", "https://example.com/feed2"],
          pageUrls: ["https://example.com/page1"],
          updatedSinceDays: 15,
          maxItemsPerRun: 50,
          updateDetection: "page_hash",
        },
      },
    });

    render(<LoversLabRulePanel />);

    const gameInput = screen.getByPlaceholderText("rules.loverslab.gameLabelPlaceholder");
    expect(gameInput).toHaveValue("skyrim");

    const feedTextarea = screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder");
    expect(feedTextarea).toHaveValue("https://example.com/feed1\nhttps://example.com/feed2");

    expect(screen.queryByPlaceholderText("rules.loverslab.pageUrlsPlaceholder")).not.toBeInTheDocument();
    const updatedInput = screen.getByPlaceholderText("rules.loverslab.updatedSinceDaysPlaceholder");
    expect(updatedInput).toHaveValue(15);

    await waitFor(() => {
      const state = useRuleEditorStore.getState().draft.loverslabDraft;
      expect(state.accessMode).toBe("rss");
      expect(state.pageUrls).toEqual([]);
    });
  });
});
