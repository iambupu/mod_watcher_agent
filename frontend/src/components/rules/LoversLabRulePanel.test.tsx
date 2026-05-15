import { describe, it, expect, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
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

  it("access_mode_switching_shows_feed", async () => {
    const user = userEvent.setup();
    const { container } = render(<LoversLabRulePanel />);

    expect(screen.queryByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).not.toBeInTheDocument();

    const select = container.querySelectorAll("select")[0] as HTMLSelectElement;
    await user.selectOptions(select, "feed");

    expect(screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).toBeInTheDocument();
  });

  it("access_mode_switching_hides_page", async () => {
    const user = userEvent.setup();
    const { container } = render(<LoversLabRulePanel />);

    const select = container.querySelectorAll("select")[0] as HTMLSelectElement;
    await user.selectOptions(select, "feed");

    expect(screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("rules.loverslab.pageUrlsPlaceholder")).not.toBeInTheDocument();
  });

  it("renders_feed_urls", async () => {
    const user = userEvent.setup();
    const { container } = render(<LoversLabRulePanel />);

    const select = container.querySelectorAll("select")[0] as HTMLSelectElement;
    await user.selectOptions(select, "both");

    expect(screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("rules.loverslab.pageUrlsPlaceholder")).toBeInTheDocument();
  });

  it("renders_page_urls", async () => {
    const user = userEvent.setup();
    const { container } = render(<LoversLabRulePanel />);

    const select = container.querySelectorAll("select")[0] as HTMLSelectElement;
    await user.selectOptions(select, "page");

    expect(screen.queryByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("rules.loverslab.pageUrlsPlaceholder")).toBeInTheDocument();
  });

  it("reads_from_store", () => {
    useRuleEditorStore.setState({
      draft: {
        ...useRuleEditorStore.getState().draft,
        loverslabDraft: {
          gameLabel: "skyrim",
          accessMode: "both",
          feedUrls: ["https://example.com/feed1", "https://example.com/feed2"],
          pageUrls: ["https://example.com/page1"],
          maxItemsPerRun: 50,
          updateDetection: "timestamp",
        },
      },
    });

    render(<LoversLabRulePanel />);

    const gameInput = screen.getByPlaceholderText("rules.loverslab.gameLabelPlaceholder");
    expect(gameInput).toHaveValue("skyrim");

    const feedTextarea = screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder");
    expect(feedTextarea).toHaveValue("https://example.com/feed1\nhttps://example.com/feed2");

    const pageTextarea = screen.getByPlaceholderText("rules.loverslab.pageUrlsPlaceholder");
    expect(pageTextarea).toHaveValue("https://example.com/page1");
  });
});
