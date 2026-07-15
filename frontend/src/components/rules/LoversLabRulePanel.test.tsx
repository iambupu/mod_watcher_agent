import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { LoversLabRulePanel } from "./LoversLabRulePanel";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("LoversLabRulePanel", () => {
  beforeEach(() => {
    useRuleEditorStore.getState().resetDraft();
    useRuleEditorStore.getState().switchSource("loverslab");
  });

  it("renders RSS controls without browser scraping actions", () => {
    render(<LoversLabRulePanel />);

    expect(screen.getByPlaceholderText("rules.loverslab.gameLabelPlaceholder")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder")).toBeInTheDocument();
    expect(screen.queryByText("rules.loverslab.browserAccess")).not.toBeInTheDocument();
    expect(screen.queryByText("rules.loverslab.openLoginBrowser")).not.toBeInTheDocument();
    expect(screen.queryByText("rules.loverslab.testCategory")).not.toBeInTheDocument();
  });

  it("updates RSS feed URLs", async () => {
    const user = userEvent.setup();
    render(<LoversLabRulePanel />);

    const textarea = screen.getByPlaceholderText("rules.loverslab.feedUrlsPlaceholder");
    await user.type(textarea, "https://www.loverslab.com/files/rss/example.xml/");

    expect(useRuleEditorStore.getState().draft.loverslabDraft.feedUrls).toEqual([
      "https://www.loverslab.com/files/rss/example.xml/",
    ]);
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

  it("offers only RSS-compatible update detection modes", () => {
    render(<LoversLabRulePanel />);

    expect(screen.getByRole("option", { name: "rules.loverslab.updateDetection.publishedTime" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "rules.loverslab.updateDetection.updatedTime" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "rules.loverslab.updateDetection.pageHash" })).not.toBeInTheDocument();
  });
});
