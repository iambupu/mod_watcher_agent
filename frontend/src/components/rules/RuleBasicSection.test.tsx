import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { RuleBasicSection } from "./RuleBasicSection";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe("RuleBasicSection", () => {
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
      activeSource: "nexusmods",
      isDirty: false,
      editingRuleId: null,
    });
  });

  it("renders_name_input", () => {
    render(<RuleBasicSection />);
    const input = screen.getByPlaceholderText("rules.name");
    expect(input).toBeInTheDocument();
    expect(input).toHaveValue("");
  });

  it("name_required_validation", async () => {
    const user = userEvent.setup();
    render(<RuleBasicSection />);

    const input = screen.getByPlaceholderText("rules.name");
    await user.click(input);
    await user.tab();

    expect(screen.getByText("rules.validation.nameRequired")).toBeInTheDocument();
  });

  it("interval_minutes_updates_store", async () => {
    const user = userEvent.setup();
    render(<RuleBasicSection />);

    const intervalInput = screen.getByRole("spinbutton", { name: "rules.basic.intervalMinutesLabel" });
    await user.clear(intervalInput);
    await user.type(intervalInput, "15");

    expect(useRuleEditorStore.getState().draft.intervalMinutes).toBe(15);
  });

  it("reads_from_store", () => {
    useRuleEditorStore.setState({
      draft: {
        ...useRuleEditorStore.getState().draft,
        name: "My Test Rule",
        enabled: false,
      },
    });

    render(<RuleBasicSection />);

    const input = screen.getByPlaceholderText("rules.name");
    expect(input).toHaveValue("My Test Rule");
  });
});
