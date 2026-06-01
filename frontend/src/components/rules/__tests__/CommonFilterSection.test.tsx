import { describe, it, expect, beforeEach, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { KeywordFilterEditor } from "../KeywordFilterEditor";
import { MetricFilterFields } from "../MetricFilterFields";
import { AdultPolicyField } from "../AdultPolicyField";
import { MissingMetricsPolicyField } from "../MissingMetricsPolicyField";
import { LlmFilterSection } from "../LlmFilterSection";
import { CommonFilterSection } from "../CommonFilterSection";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { CommonRuleFilters } from "@/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

beforeEach(() => {
  useRuleEditorStore.setState({
    draft: {
      name: "test",
      enabled: true,
      intervalMinutes: 360,
      commonFilters: {},
      nexusmodsDraft: { gameDomainName: "", updatedSinceDays: 7 },
      loverslabDraft: { gameLabel: "" },
      notification: { enabled: true, mode: "instant" },
    },
    activeSource: "nexusmods",
    isDirty: false,
    editingRuleId: null,
  });
});

describe("KeywordFilterEditor", () => {
  it("renders include and exclude keyword sections", () => {
    render(
      <KeywordFilterEditor
        includeKeywords={[]}
        excludeKeywords={[]}
        onChange={() => undefined}
      />,
    );
    expect(screen.getByText("rules.filters.keywordFilter")).toBeInTheDocument();
    expect(screen.getByText("rules.includeKeywords")).toBeInTheDocument();
    expect(screen.getByText("rules.excludeKeywords")).toBeInTheDocument();
  });

  it("renders existing keywords as tags", () => {
    render(
      <KeywordFilterEditor
        includeKeywords={["skyrim", "fallout"]}
        excludeKeywords={["nsfw"]}
        onChange={() => {}}
      />,
    );
    expect(screen.getByText("skyrim")).toBeInTheDocument();
    expect(screen.getByText("fallout")).toBeInTheDocument();
    expect(screen.getByText("nsfw")).toBeInTheDocument();
  });

  it("adds keyword when Enter pressed in include input", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(
      <KeywordFilterEditor
        includeKeywords={[]}
        excludeKeywords={[]}
        onChange={(p) => (changed = p)}
      />,
    );
    const inputs = screen.getAllByPlaceholderText("rules.includeKeywords...");
    fireEvent.change(inputs[0], { target: { value: "test" } });
    fireEvent.keyDown(inputs[0], { key: "Enter" });
    expect(changed).toEqual({ includeKeywords: ["test"] });
  });

  it("adds keyword on blur when input is not empty", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(
      <KeywordFilterEditor
        includeKeywords={[]}
        excludeKeywords={[]}
        onChange={(p) => (changed = p)}
      />,
    );
    const inputs = screen.getAllByPlaceholderText("rules.excludeKeywords...");
    fireEvent.change(inputs[0], { target: { value: "nsfw" } });
    fireEvent.blur(inputs[0]);
    expect(changed).toEqual({ excludeKeywords: ["nsfw"] });
  });

  it("removes keyword when X button clicked", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(
      <KeywordFilterEditor
        includeKeywords={["remove_me"]}
        excludeKeywords={[]}
        onChange={(p) => (changed = p)}
      />,
    );
    const removeBtn = screen.getAllByRole("button")[0];
    fireEvent.click(removeBtn);
    expect(changed).toEqual({ includeKeywords: [] });
  });
});

describe("MetricFilterFields", () => {
  it("renders 4 number input fields", () => {
    render(
      <MetricFilterFields onChange={() => {}} />,
    );
    expect(screen.getByText("rules.minDownloads")).toBeInTheDocument();
    expect(screen.getByText("rules.minEndorsements")).toBeInTheDocument();
    expect(screen.getByText("rules.minLikes")).toBeInTheDocument();
    expect(screen.getByText("rules.filters.updatedWithinDays")).toBeInTheDocument();
  });

  it("updates minDownloads on input change", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(
      <MetricFilterFields onChange={(p) => (changed = p)} />,
    );
    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "100" } });
    expect(changed).toEqual({ minDownloads: 100 });
  });

  it("clears value when input is emptied", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(
      <MetricFilterFields minDownloads={50} onChange={(p) => (changed = p)} />,
    );
    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[0], { target: { value: "" } });
    expect(changed).toEqual({ minDownloads: undefined });
  });

  it("does not allow updatedWithinDays below backend minimum", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(<MetricFilterFields onChange={(p) => (changed = p)} />);

    const inputs = screen.getAllByRole("spinbutton");
    fireEvent.change(inputs[3], { target: { value: "0" } });

    expect(changed).toBeNull();
  });
});

describe("AdultPolicyField", () => {
  it("renders select with 3 adult policy options", () => {
    render(<AdultPolicyField onChange={() => {}} />);
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(3);
  });

  it("calls onChange with correct value on selection", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(<AdultPolicyField onChange={(p) => (changed = p)} />);
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "only" } });
    expect(changed).toEqual({ adultPolicy: "only" });
  });
});

describe("MissingMetricsPolicyField", () => {
  it("renders select with pass/reject options", () => {
    render(<MissingMetricsPolicyField onChange={() => {}} />);
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    const options = screen.getAllByRole("option");
    expect(options).toHaveLength(2);
  });

  it("calls onChange when reject is selected", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(<MissingMetricsPolicyField onChange={(p) => (changed = p)} />);
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "reject" } });
    expect(changed).toEqual({ missingMetricsPolicy: "reject" });
  });
});

describe("LlmFilterSection", () => {
  it("renders all controls by default", () => {
    render(<LlmFilterSection onChange={() => {}} />);
    expect(screen.getByText("rules.filters.llmFilterEnabled")).toBeInTheDocument();
    expect(screen.getByText("rules.filters.llmPrompt")).toBeInTheDocument();
    expect(screen.getByText("rules.filters.llmMode")).toBeInTheDocument();
    expect(screen.getByText(/rules\.filters\.llmConfidence/)).toBeInTheDocument();
  });

  it("toggles switch and updates llmFilter.enabled", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(<LlmFilterSection onChange={(p) => (changed = p)} />);
    const toggle = screen.getByRole("switch");
    fireEvent.click(toggle);
    expect(changed).toMatchObject({ llmFilter: { enabled: true } });
  });

  it("shows confidence slider value", () => {
    render(
      <LlmFilterSection
        llmFilter={{ enabled: true, mode: "assist_only", minConfidence: 0.7 }}
        onChange={() => {}}
      />,
    );
    const slider = screen.getByRole("slider");
    expect(slider).toHaveValue("0.7");
    expect(screen.getByText(/70%/)).toBeInTheDocument();
  });

  it("clamps invalid confidence values", () => {
    let changed: Partial<CommonRuleFilters> | null = null;
    render(
      <LlmFilterSection
        llmFilter={{ enabled: true, mode: "assist_only", minConfidence: Number.NaN }}
        onChange={(p) => (changed = p)}
      />,
    );

    expect(screen.getByText(/50%/)).toBeInTheDocument();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "2" } });
    expect(changed).toMatchObject({ llmFilter: { minConfidence: 1 } });
  });
});

describe("CommonFilterSection", () => {
  it("renders with store data and integrates deterministic filter sub-components", () => {
    render(<CommonFilterSection />);
    expect(screen.getByText("rules.filters.keywordFilter")).toBeInTheDocument();
    expect(screen.getByText("rules.metrics")).toBeInTheDocument();
    expect(screen.getByText("rules.adultPolicy")).toBeInTheDocument();
    expect(screen.getByText("rules.filters.missingMetricsPolicy")).toBeInTheDocument();
    expect(screen.queryByText("rules.filters.llmFilter")).not.toBeInTheDocument();
  });
});
