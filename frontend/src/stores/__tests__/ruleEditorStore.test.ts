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
});
