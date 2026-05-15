import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RuleEditorPage } from "@/components/rules/RuleEditorPage";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
    i18n: { language: "en-US" },
  }),
}));

vi.mock("@/api/rules", () => ({
  fetchRules: vi.fn().mockResolvedValue([]),
  fetchRuleById: vi.fn().mockResolvedValue({
    id: 1,
    name: "Test Rule",
    enabled: true,
    source: "nexusmods",
    sourceConfig: { gameDomainName: "skyrim", updatedSinceDays: 7 },
    filters: { adultPolicy: "exclude" },
    notification: { enabled: true, mode: "instant" },
    createdAt: "2025-01-01T00:00:00Z",
    updatedAt: "2025-01-01T00:00:00Z",
  }),
  createRule: vi.fn(),
  updateRule: vi.fn(),
  testRule: vi.fn().mockResolvedValue({
    scanned: 10,
    normalized: 8,
    passedDeterministicFilters: 5,
    passedLlmFilters: 0,
    rejectedReasons: [],
    items: [],
  }),
  deleteRule: vi.fn(),
  toggleRule: vi.fn(),
  runRule: vi.fn(),
}));

function renderWithRoute(route: string) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });

  return {
    queryClient,
    ...render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={[route]}>
          <Routes>
            <Route path="/rules/new" element={<RuleEditorPage />} />
            <Route path="/rules/:id/edit" element={<RuleEditorPage />} />
          </Routes>
        </MemoryRouter>
      </QueryClientProvider>,
    ),
  };
}

describe("RuleEditorPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useRuleEditorStore.getState().resetDraft();
  });

  it("renders_create_mode", () => {
    renderWithRoute("/rules/new");

    expect(screen.getByText("rules.newRule")).toBeInTheDocument();
    expect(screen.getByText("rules.basicInfo")).toBeInTheDocument();
    expect(screen.getByText("rules.source")).toBeInTheDocument();
    expect(screen.getByText("rules.filters")).toBeInTheDocument();
    expect(screen.getByText("rules.notification")).toBeInTheDocument();
    expect(screen.getByText("rules.actions.saveRule")).toBeInTheDocument();
    expect(screen.getByText("common.cancel")).toBeInTheDocument();
    expect(screen.getByText("rules.actions.testRule")).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText("rules.name");
    expect(nameInput).toBeInTheDocument();
    expect(nameInput).toHaveValue("");
  });

  it("renders_edit_mode", async () => {
    renderWithRoute("/rules/1/edit");

    const heading = await screen.findByText("rules.editRule");
    expect(heading).toBeInTheDocument();

    const nameInput = screen.getByPlaceholderText("rules.name");
    expect(nameInput).toHaveValue("Test Rule");

    const storeState = useRuleEditorStore.getState();
    expect(storeState.draft.name).toBe("Test Rule");
    expect(storeState.activeSource).toBe("nexusmods");
  });

  it("tab_switch_updates_panel", async () => {
    const user = userEvent.setup();

    renderWithRoute("/rules/new");

    const nexusText = "rules.sourceTabs.nexusmods";
    const loversLabText = "rules.sourceTabs.loverslab";

    const nexusModsTab = screen.getByRole("tab", { name: nexusText });
    const loversLabTab = screen.getByRole("tab", { name: loversLabText });

    expect(nexusModsTab).toBeInTheDocument();
    expect(loversLabTab).toBeInTheDocument();

    expect(nexusModsTab.className).toContain("bg-blue-600");

    await user.click(loversLabTab);

    await waitFor(() => {
      expect(loversLabTab.className).toContain("bg-blue-600");
      expect(nexusModsTab.className).not.toContain("bg-blue-600");
    });
  });
});
