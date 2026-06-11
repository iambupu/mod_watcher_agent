// 中文注释：提供规则编辑器里的 LoversLabRulePanel.test 表单组件。

import { describe, it, expect, beforeEach, vi } from "vitest";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { LoversLabRulePanel } from "./LoversLabRulePanel";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

vi.mock("@/api/loverslab-browser", () => ({
  fetchLoversLabBrowserStatus: vi.fn().mockResolvedValue({
    profileExists: false,
    playwrightInstalled: true,
    browserInstalled: true,
    lastCheckStatus: null,
    lastCheckAt: null,
  }),
  openLoversLabLogin: vi.fn().mockResolvedValue({
    status: "ok",
    url: "https://www.loverslab.com/",
    finalUrl: "https://www.loverslab.com/",
    title: "LoversLab",
  }),
  checkLoversLabSession: vi.fn().mockResolvedValue({
    status: "ok",
    url: "https://www.loverslab.com/files/",
    finalUrl: "https://www.loverslab.com/files/",
    title: "LoversLab",
  }),
  installLoversLabChromium: vi.fn().mockResolvedValue({
    success: true,
    status: "ok",
    message: "Chromium installed",
    stdout: "",
    stderr: "",
  }),
  testLoversLabCategory: vi.fn().mockResolvedValue({
    status: "ok",
    title: "Category",
    finalUrl: "https://www.loverslab.com/files/category/110-skyrim/",
    itemsCount: 1,
    items: [
      {
        fileId: "123",
        title: "Sample",
        url: "https://www.loverslab.com/files/file/123-sample/",
        author: "Author",
        updatedAt: "2026-05-01T00:00:00Z",
        thumbnailUrl: "",
        summary: "",
        contentHash: "hash",
      },
    ],
  }),
  saveLoversLabSnapshot: vi.fn().mockResolvedValue({
    status: "ok",
    path: "data/snapshots/loverslab/sample.html",
    title: "Category",
    finalUrl: "https://www.loverslab.com/files/category/110-skyrim/",
  }),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

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
          browserProfile: "loverslab",
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
    expect(screen.getByText("rules.loverslab.rssModeHelp")).toBeInTheDocument();
    expect(screen.queryByText("rules.loverslab.browserAccess")).not.toBeInTheDocument();
    expect(screen.queryByText("rules.loverslab.installChromium")).not.toBeInTheDocument();
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

  it("renders_page_urls_and_feed_urls_for_both_mode", async () => {
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

    expect(screen.getByPlaceholderText("rules.loverslab.pageUrlsPlaceholder")).toHaveValue("https://example.com/page1");
    expect(screen.getByText("rules.loverslab.browserAccess")).toBeInTheDocument();
    expect(screen.getByText("rules.loverslab.pageModeHelp")).toBeInTheDocument();
    expect(screen.getByText("rules.loverslab.saveSnapshot")).toBeInTheDocument();
    const updatedInput = screen.getByPlaceholderText("rules.loverslab.updatedSinceDaysPlaceholder");
    expect(updatedInput).toHaveValue(15);

    await waitFor(() => {
      const state = useRuleEditorStore.getState().draft.loverslabDraft;
      expect(state.accessMode).toBe("both");
      expect(state.pageUrls).toEqual(["https://example.com/page1"]);
    });
  });

  it("clamps numeric settings to backend limits", async () => {
    const user = userEvent.setup();
    render(<LoversLabRulePanel />);

    const updatedInput = screen.getByPlaceholderText("rules.loverslab.updatedSinceDaysPlaceholder");
    await user.clear(updatedInput);
    await user.type(updatedInput, "999");

    const maxItemsInput = screen.getAllByRole("spinbutton").find((input) => input !== updatedInput);
    expect(maxItemsInput).toBeDefined();
    await user.clear(maxItemsInput!);
    await user.type(maxItemsInput!, "999");

    const state = useRuleEditorStore.getState().draft.loverslabDraft;
    expect(state.updatedSinceDays).toBe(365);
    expect(state.maxItemsPerRun).toBe(100);
  });

  it("hides_rss_fields_for_page_mode", async () => {
    useRuleEditorStore.setState({
      draft: {
        ...useRuleEditorStore.getState().draft,
        loverslabDraft: {
          gameLabel: "skyrim",
          accessMode: "page",
          feedUrls: ["https://example.com/feed1"],
          pageUrls: ["https://example.com/page1"],
          updatedSinceDays: 15,
          maxItemsPerRun: 50,
          updateDetection: "page_hash",
        },
      },
    });

    render(<LoversLabRulePanel />);

    expect(screen.queryByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).not.toBeInTheDocument();
    expect(screen.queryByText("rules.loverslab.rssNotice")).not.toBeInTheDocument();
    expect(screen.queryByText("rules.loverslab.updatedSinceDaysHelp")).not.toBeInTheDocument();
    expect(screen.getByPlaceholderText("rules.loverslab.pageUrlsPlaceholder")).toHaveValue("https://example.com/page1");
    expect(screen.getByText("rules.loverslab.pageUpdatedSinceDaysHelp")).toBeInTheDocument();
    await act(async () => {});
  });
});
