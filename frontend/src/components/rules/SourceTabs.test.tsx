// 中文注释：提供规则编辑器里的 SourceTabs.test 表单组件。

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceTabs } from "./SourceTabs";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        "rules.sourceTabs.nexusmods": "NexusMods",
        "rules.sourceTabs.loverslab": "LoversLab",
      };
      return map[key] || key;
    },
  }),
}));

const mockSwitchSource = vi.fn();
let mockActiveSource = "nexusmods" as "nexusmods" | "loverslab";

vi.mock("@/stores/ruleEditorStore", () => ({
  useRuleEditorStore: (selector: (state: any) => any) => {
    const store = {
      activeSource: mockActiveSource,
      switchSource: mockSwitchSource,
    };
    return selector(store);
  },
}));

describe("SourceTabs", () => {
  beforeEach(() => {
    mockActiveSource = "nexusmods";
    mockSwitchSource.mockClear();
  });

  it("renders both tabs", () => {
    render(<SourceTabs />);
    expect(screen.getByRole("tab", { name: "NexusMods" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "LoversLab" })).toBeInTheDocument();
  });

  it("switches tab on click", async () => {
    const user = userEvent.setup();
    render(<SourceTabs />);
    await user.click(screen.getByRole("tab", { name: "LoversLab" }));
    expect(mockSwitchSource).toHaveBeenCalledWith("loverslab");
  });

  it("active tab is highlighted", () => {
    mockActiveSource = "nexusmods";
    render(<SourceTabs />);
    const nexusTab = screen.getByRole("tab", { name: "NexusMods" });
    const loversTab = screen.getByRole("tab", { name: "LoversLab" });
    expect(nexusTab).toHaveAttribute("aria-selected", "true");
    expect(loversTab).toHaveAttribute("aria-selected", "false");
  });

  it("preserves common filters on switch", async () => {
    const user = userEvent.setup();
    render(<SourceTabs />);
    await user.click(screen.getByRole("tab", { name: "LoversLab" }));
    expect(mockSwitchSource).toHaveBeenCalledTimes(1);
    expect(mockSwitchSource).toHaveBeenCalledWith("loverslab");
  });
});
