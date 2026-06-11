// 中文注释：提供规则编辑器里的 RuleTestResultPanel.test 表单组件。

import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RuleTestResultPanel } from "@/components/rules/RuleTestResultPanel";
import type { RuleTestResponse } from "@/types";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, options?: Record<string, unknown> | string) => {
      if (key === "rules.test.title") return "Rule Test Results";
      if (key === "rules.test.scanned") return "Scanned";
      if (key === "rules.test.normalized") return "Normalized";
      if (key === "rules.test.passedDeterministic") return "Passed Deterministic Filter";
      if (key === "rules.test.passedLlm") return "Passed LLM Filter";
      if (key === "rules.test.rejectedReasons") return "Rejected Reasons";
      if (key === "rules.test.rejectedItems") return `Rejected Items ${(options as Record<string, unknown>)?.count}`;
      if (key === "rules.test.llmFeedback") return "LLM Feedback";
      if (key === "rules.test.noResults") return "No Results";
      if (key === "rules.matchCount") return `Matched ${(options as Record<string, unknown>)?.count} items`;
      if (typeof options === "string") return options;
      return key;
    },
    i18n: { language: "en-US" },
  }),
}));

function makeResult(overrides?: Partial<RuleTestResponse>): RuleTestResponse {
  return {
    scanned: 100,
    normalized: 95,
    passedDeterministicFilters: 42,
    passedLlmFilters: 30,
    rejectedReasons: {},
    rejectedItems: [],
    items: [],
    ...overrides,
  };
}

describe("RuleTestResult", () => {
  it("renders_stats", () => {
    render(
      <RuleTestResultPanel
        result={makeResult({
          scanned: 100,
          normalized: 95,
          passedDeterministicFilters: 42,
          passedLlmFilters: 30,
        })}
      />
    );

    expect(screen.getByText("Rule Test Results")).toBeInTheDocument();
    expect(screen.getByText("100")).toBeInTheDocument();
    expect(screen.getByText("95")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("30")).toBeInTheDocument();
  });

  it("renders_rejected_reasons", () => {
    render(
      <RuleTestResultPanel
        result={makeResult({
          rejectedReasons: {
            "Downloads too low": 2,
            "Adult content excluded": 1,
          },
        })}
      />
    );

    expect(screen.getByText("Rejected Reasons")).toBeInTheDocument();
    expect(screen.getByText("Downloads too low: 2")).toBeInTheDocument();
    expect(screen.getByText("Adult content excluded: 1")).toBeInTheDocument();
  });

  it("renders_rejected_item_details", () => {
    render(
      <RuleTestResultPanel
        result={makeResult({
          rejectedReasons: { llm_rejected: 1 },
          rejectedItems: [
            {
              source: "nexusmods",
              externalId: "1001",
              title: "Rejected Mod",
              game: "Skyrim",
              url: "https://example.com/mod/1001",
              reason: "llm_rejected",
              stage: "llm",
              llmFeedback: "not relevant",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Rejected Items 1")).toBeInTheDocument();
    expect(screen.getByText("Rejected Mod")).toBeInTheDocument();
    expect(screen.getByText("LLM Feedback: not relevant")).toBeInTheDocument();
  });

  it("limits_rejected_item_details_to_five", () => {
    const rejectedItems = Array.from({ length: 7 }, (_, idx) => ({
      source: "loverslab" as const,
      externalId: `rejected-${idx + 1}`,
      title: `Rejected Mod ${idx + 1}`,
      game: "X-Change Life",
      url: `https://example.com/rejected/${idx + 1}`,
      reason: "already_exists_or_ignored",
      stage: "deduplicate",
    }));

    render(
      <RuleTestResultPanel
        result={makeResult({
          rejectedReasons: { already_exists_or_ignored: 7 },
          rejectedItems,
        })}
      />
    );

    expect(screen.getByText("Rejected Items 7")).toBeInTheDocument();
    expect(screen.getAllByText(/Rejected Mod \d/)).toHaveLength(5);
    expect(screen.getByText("Rejected Mod 5")).toBeInTheDocument();
    expect(screen.queryByText("Rejected Mod 6")).not.toBeInTheDocument();
  });

  it("renders_item_list", () => {
    render(
      <RuleTestResultPanel
        result={makeResult({
          items: [
            {
              id: 1,
              source: "nexusmods",
              external_id: "mod-001",
              game: "Skyrim",
              title: "Awesome Sword",
              url: "https://nexusmods.com/skyrim/mods/1",
              tags_json: "[]",
              ignored: false,
              first_seen_at: "2024-01-01T00:00:00Z",
              last_seen_at: "2024-01-01T00:00:00Z",
            },
            {
              id: 2,
              source: "loverslab",
              external_id: "mod-002",
              game: "Fallout 4",
              title: "Cool Armor",
              url: "https://loverslab.com/files/file/2",
              tags_json: "[]",
              ignored: false,
              first_seen_at: "2024-01-01T00:00:00Z",
              last_seen_at: "2024-01-01T00:00:00Z",
            },
          ],
        })}
      />
    );

    expect(screen.getByText("Matched 2 items")).toBeInTheDocument();
    expect(screen.getByText("Awesome Sword")).toBeInTheDocument();
    expect(screen.getByText("mod-001")).toBeInTheDocument();
    expect(screen.getByText("Skyrim")).toBeInTheDocument();
    expect(screen.getByText("https://nexusmods.com/skyrim/mods/1")).toBeInTheDocument();
    expect(screen.getByText("Cool Armor")).toBeInTheDocument();
    expect(screen.getByText("Fallout 4")).toBeInTheDocument();
    expect(screen.getAllByText("Passed")).toHaveLength(2);
  });

  it("limits_matched_item_list_to_five", () => {
    const items = Array.from({ length: 7 }, (_, idx) => ({
      id: idx + 1,
      source: "loverslab" as const,
      external_id: `mod-${idx + 1}`,
      game: "X-Change Life",
      title: `Matched Mod ${idx + 1}`,
      url: `https://example.com/mod/${idx + 1}`,
      tags_json: "[]",
      ignored: false,
      first_seen_at: "2024-01-01T00:00:00Z",
      last_seen_at: "2024-01-01T00:00:00Z",
    }));

    render(<RuleTestResultPanel result={makeResult({ items })} />);

    expect(screen.getByText("Matched 7 items")).toBeInTheDocument();
    expect(screen.getAllByText(/Matched Mod \d/)).toHaveLength(5);
    expect(screen.getByText("Matched Mod 5")).toBeInTheDocument();
    expect(screen.queryByText("Matched Mod 6")).not.toBeInTheDocument();
    expect(screen.getAllByText("Passed")).toHaveLength(5);
  });

  it("renders_empty_state", () => {
    const { rerender } = render(<RuleTestResultPanel result={null} />);
    expect(screen.getByText("No Results")).toBeInTheDocument();

    rerender(
      <RuleTestResultPanel
        result={makeResult({ scanned: 0, items: [] })}
      />
    );
    expect(screen.getByText("No Results")).toBeInTheDocument();
  });
});
