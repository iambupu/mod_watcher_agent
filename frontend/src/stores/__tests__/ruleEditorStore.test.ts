// 中文注释：定义 ruleEditorStore.test 的 Zustand 状态边界。

import { act } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { useRuleEditorStore } from "@/stores/ruleEditorStore";

describe("ruleEditorStore", () => {
  beforeEach(() => {
    act(() => {
      useRuleEditorStore.getState().resetDraft();
    });
  });

  it("marks a new draft dirty when switching source", () => {
    expect(useRuleEditorStore.getState().isDirty).toBe(false);

    act(() => {
      useRuleEditorStore.getState().switchSource("loverslab");
    });

    expect(useRuleEditorStore.getState().activeSource).toBe("loverslab");
    expect(useRuleEditorStore.getState().isDirty).toBe(true);
  });

  it("does not mark a clean draft dirty when switching to the current source", () => {
    act(() => {
      useRuleEditorStore.getState().switchSource("nexusmods");
    });

    expect(useRuleEditorStore.getState().activeSource).toBe("nexusmods");
    expect(useRuleEditorStore.getState().isDirty).toBe(false);
  });

  it("drops legacy browser scraping fields when loading a LoversLab rule", () => {
    act(() => {
      useRuleEditorStore.getState().loadRule({
        id: 1,
        name: "Legacy LoversLab rule",
        enabled: true,
        intervalMinutes: 360,
        source: "loverslab",
        sourceConfig: {
          gameLabel: "Skyrim SE",
          feedUrls: ["https://www.loverslab.com/files/rss/"],
          accessMode: "both",
          pageUrls: ["https://www.loverslab.com/files/category/110-skyrim/"],
          browserProfile: "loverslab",
          updateDetection: "page_hash",
        },
        filters: {},
        notification: { enabled: false, mode: "instant" },
        createdAt: "2026-01-01T00:00:00Z",
        updatedAt: "2026-01-01T00:00:00Z",
      } as never);
    });

    expect(useRuleEditorStore.getState().getSubmitData().sourceConfig).toEqual({
      gameLabel: "Skyrim SE",
      feedUrls: ["https://www.loverslab.com/files/rss/"],
      updatedSinceDays: 30,
      maxItemsPerRun: 50,
      updateDetection: "published_time",
    });
  });
});
