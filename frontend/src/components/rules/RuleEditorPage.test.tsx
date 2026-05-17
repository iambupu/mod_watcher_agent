import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RuleEditorPage } from "@/components/rules/RuleEditorPage";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import { createRule, fetchRuleById } from "@/api/rules";

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
    rejectedReasons: {},
    rejectedItems: [],
    items: [],
  }),
  deleteRule: vi.fn(),
  toggleRule: vi.fn(),
  runRule: vi.fn(),
}));

function renderWithRoute(route: string) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: 1000 * 60 * 5 },
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

function renderWithRouteAndClient(route: string, queryClient: QueryClient) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[route]}>
        <Routes>
          <Route path="/rules/new" element={<RuleEditorPage />} />
          <Route path="/rules/:id/edit" element={<RuleEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
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

  it("refetches latest rule when opening edit page even if cached", async () => {
    vi.mocked(fetchRuleById).mockResolvedValueOnce({
      id: 1,
      name: "Fresh Rule",
      enabled: true,
      intervalMinutes: 360,
      source: "nexusmods",
      sourceConfig: { gameDomainName: "skyrim", updatedSinceDays: 7 },
      filters: { adultPolicy: "exclude" },
      notification: { enabled: true, mode: "instant" },
      createdAt: "2025-01-01T00:00:00Z",
      updatedAt: "2025-01-01T00:00:00Z",
    });

    const queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false, staleTime: 1000 * 60 * 5 },
        mutations: { retry: false },
      },
    });
    queryClient.setQueryData(["rule", 1], {
      id: 1,
      name: "Stale Cached Rule",
      enabled: true,
      source: "nexusmods",
      sourceConfig: { gameDomainName: "skyrim", updatedSinceDays: 7 },
      filters: { adultPolicy: "exclude" },
      notification: { enabled: true, mode: "instant" },
      createdAt: "2025-01-01T00:00:00Z",
      updatedAt: "2025-01-01T00:00:00Z",
    });
    renderWithRouteAndClient("/rules/1/edit", queryClient);

    await waitFor(() => {
      expect(fetchRuleById).toHaveBeenCalledWith(1);
      expect(useRuleEditorStore.getState().draft.name).toBe("Fresh Rule");
    });
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

  it("saves pending Nexus category and tag input before submit", async () => {
    const user = userEvent.setup();
    vi.mocked(createRule).mockResolvedValueOnce({
      id: 2,
      name: "Nexus Rule",
      enabled: true,
      intervalMinutes: 360,
      source: "nexusmods",
      sourceConfig: {
        gameDomainName: "skyrimspecialedition",
        updatedSinceDays: 7,
        categoryNames: ["Armor"],
        tags: ["lore-friendly"],
      },
      filters: {},
      notification: { enabled: true, mode: "instant" },
      createdAt: "2025-01-01T00:00:00Z",
      updatedAt: "2025-01-01T00:00:00Z",
    });

    renderWithRoute("/rules/new");

    await user.type(screen.getByPlaceholderText("rules.name"), "Nexus Rule");
    await user.type(
      screen.getByPlaceholderText("rules.nexusmods.gameDomainNamePlaceholder"),
      "skyrimspecialedition",
    );
    await user.type(
      screen.getByPlaceholderText("rules.nexusmods.categoryNamesPlaceholder"),
      "Armor",
    );
    await user.type(
      screen.getByPlaceholderText("rules.nexusmods.tagsPlaceholder"),
      "lore-friendly",
    );
    await user.click(screen.getByText("rules.actions.saveRule"));

    await waitFor(() => {
      expect(vi.mocked(createRule).mock.calls[0]?.[0]).toEqual(
        expect.objectContaining({
          sourceConfig: expect.objectContaining({
            categoryNames: ["Armor"],
            tags: ["lore-friendly"],
          }),
        }),
      );
    });
  });
});
