// 中文注释：提供规则编辑器里的 NexusModsRulePanel.test 表单组件。

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NexusModsRulePanel } from "../NexusModsRulePanel";

const mockUpdateNexusConfig = vi.fn();

function buildMockStore(overrides: Record<string, unknown> = {}) {
  return {
    draft: {
      nexusmodsDraft: {
        gameDomainName: "",
        updatedSinceDays: 7,
        queryMode: undefined,
        sortBy: undefined,
        categoryNames: [],
        tags: [],
        ...overrides,
      },
    },
    updateNexusConfig: mockUpdateNexusConfig,
  };
}

vi.mock("@/stores/ruleEditorStore", () => ({
  useRuleEditorStore: vi.fn(),
}));

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => {
      const map: Record<string, string> = {
        "rules.nexusmods.gameDomainName": "Game Domain Name",
        "rules.nexusmods.gameDomainNamePlaceholder": "e.g. skyrimspecialedition",
        "rules.nexusmods.gameDomainNameHelp": "Game domain help",
        "rules.nexusmods.updatedSinceDays": "Updated Since (Days)",
        "rules.nexusmods.updatedSinceDaysPlaceholder": "e.g. 7",
        "rules.nexusmods.updatedSinceDaysHelp": "Updated days help",
        "rules.nexusmods.queryMode": "Query Mode",
        "rules.nexusmods.queryModeHelp": "Query mode help",
        "rules.nexusmods.queryModeAll": "All",
        "rules.nexusmods.queryModeUpdated": "Recently Updated",
        "rules.nexusmods.queryModeCreated": "Recently Created",
        "rules.nexusmods.sortBy": "Sort By",
        "rules.nexusmods.sortByHelp": "Sort by help",
        "rules.sortUpdatedDesc": "Updated (Desc)",
        "rules.sortCreatedDesc": "Created (Desc)",
        "rules.sortDownloadsDesc": "Downloads (Desc)",
        "rules.sortEndorsementsDesc": "Endorsements (Desc)",
        "rules.nexusmods.categoryNames": "Category Names",
        "rules.nexusmods.categoryNamesPlaceholder": "Enter category names",
        "rules.nexusmods.categoryNamesHelp": "Category names help",
        "rules.nexusmods.tags": "Tags Filter",
        "rules.nexusmods.tagsPlaceholder": "Enter tags",
        "rules.nexusmods.tagsHelp": "Tags help",
        "rules.nexusmods.errors.gameDomainNameRequired": "Game domain name is required",
        "rules.nexusmods.errors.updatedSinceDaysNumeric": "Days must be a valid number",
      };
      return map[key] || key;
    },
    i18n: { language: "en-US" },
  }),
}));

import { useRuleEditorStore } from "@/stores/ruleEditorStore";

const mockedUseStore = useRuleEditorStore as unknown as ReturnType<typeof vi.fn>;

describe("NexusModsRulePanel", () => {
  beforeEach(() => {
    mockUpdateNexusConfig.mockClear();
    mockedUseStore.mockImplementation(
      (selector?: (s: unknown) => unknown) => {
        const store = buildMockStore();
        if (selector) return selector(store);
        return store;
      },
    );
  });

  it("renders required fields with red asterisk", () => {
    render(<NexusModsRulePanel />);
    expect(screen.getByText("Game Domain Name")).toBeInTheDocument();
    expect(screen.getByText("Updated Since (Days)")).toBeInTheDocument();
    const asterisks = screen.getAllByText("*");
    expect(asterisks.length).toBeGreaterThanOrEqual(2);
  });

  it("shows error when game domain name is empty", async () => {
    const user = userEvent.setup();
    render(<NexusModsRulePanel />);

    const input = screen.getByPlaceholderText("e.g. skyrimspecialedition");
    await user.click(input);
    await user.keyboard("{Tab}");

    expect(screen.getByText("Game domain name is required")).toBeInTheDocument();
  });

  it("shows error when updated since days is not numeric", async () => {
    render(<NexusModsRulePanel />);

    const input = screen.getByPlaceholderText("e.g. 7") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "abc" } });

    expect(screen.getByText("Days must be a valid number")).toBeInTheDocument();
    expect(mockUpdateNexusConfig).not.toHaveBeenCalled();
  });

  it("clamps updated since days to backend maximum", async () => {
    render(<NexusModsRulePanel />);

    const input = screen.getByPlaceholderText("e.g. 7") as HTMLInputElement;
    fireEvent.change(input, { target: { value: "999" } });

    expect(mockUpdateNexusConfig).toHaveBeenCalledWith({ updatedSinceDays: 365 });
  });

  it("renders sort by select with correct options", () => {
    render(<NexusModsRulePanel />);

    const select = screen.getByLabelText("Sort By");
    expect(select).toBeInTheDocument();

    const options = Array.from(select.querySelectorAll("option"));
    const labels = options.map((o) => o.textContent);
    expect(labels).toContain("Updated (Desc)");
    expect(labels).toContain("Created (Desc)");
    expect(labels).toContain("Downloads (Desc)");
    expect(labels).toContain("Endorsements (Desc)");
  });

  it("adds category names and tags with Enter", async () => {
    const user = userEvent.setup();
    render(<NexusModsRulePanel />);

    const categoryInput = screen.getByPlaceholderText("Enter category names");
    await user.type(categoryInput, "armor{Enter}");
    expect(mockUpdateNexusConfig).toHaveBeenCalledWith(
      expect.objectContaining({ categoryNames: ["armor"] }),
    );

    const tagsInput = screen.getByPlaceholderText("Enter tags");
    await user.type(tagsInput, "lore-friendly, hd{Enter}");
    expect(mockUpdateNexusConfig).toHaveBeenCalledWith(
      expect.objectContaining({ tags: ["lore-friendly, hd"] }),
    );
  });

  it("reads initial values from store", () => {
    mockedUseStore.mockImplementation(
      (selector?: (s: unknown) => unknown) => {
        const store = buildMockStore({
          gameDomainName: "skyrimspecialedition",
          updatedSinceDays: 30,
          categoryNames: ["armor"],
          tags: ["hd"],
        });
        if (selector) return selector(store);
        return store;
      },
    );

    render(<NexusModsRulePanel />);

    const gameInput = screen.getByPlaceholderText(
      "e.g. skyrimspecialedition",
    ) as HTMLInputElement;
    expect(gameInput.value).toBe("skyrimspecialedition");

    const daysInput = screen.getByPlaceholderText("e.g. 7") as HTMLInputElement;
    expect(daysInput.value).toBe("30");

    expect(screen.getByText("armor")).toBeInTheDocument();

    expect(screen.getByText("hd")).toBeInTheDocument();
  });
});
