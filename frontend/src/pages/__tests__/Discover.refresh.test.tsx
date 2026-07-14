import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as jobsApi from "@/api/jobs";
import * as modsApi from "@/api/mods";
import Discover from "@/pages/Discover";

vi.mock("@/api/jobs");
vi.mock("@/api/mods");
vi.mock("@/api/favorites", () => ({
  favoriteByModId: () => new Map(),
  fetchFavoriteRefs: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/components/layout/AppSidebar", () => ({ default: () => null }));
vi.mock("@/components/ModCard", () => ({ ModCard: () => null }));
vi.mock("@/hooks/useSummaryRegeneration", () => ({
  useSummaryRegeneration: () => ({ regenerateSummary: vi.fn(), regeneratingSummaryIds: new Set() }),
}));
vi.mock("@/hooks/useFavoriteToggle", () => ({
  useFavoriteToggle: () => ({ favoriteMutation: { mutate: vi.fn() } }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

describe("Discover filter synchronization", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    vi.clearAllMocks();
    vi.mocked(modsApi.fetchModGames).mockResolvedValue([]);
    vi.mocked(modsApi.fetchModCategories).mockResolvedValue([]);
    vi.mocked(modsApi.fetchMods).mockResolvedValue({ items: [], total: 0 });
    vi.mocked(jobsApi.runDiscoveryAll).mockResolvedValue({ status: "queued", job_id: 42 });
    vi.mocked(jobsApi.pollJobRun).mockResolvedValue({
      status: "completed",
      job: {
        id: 42,
        job_name: "discover_all",
        status: "succeeded",
        started_at: "2026-07-14T00:00:00Z",
        items_scanned: 10,
        items_matched: 3,
      },
    });
  });

  afterEach(() => {
    queryClient.clear();
  });

  it("refreshes game and category options after discovery updates mod data", async () => {
    const invalidateQueries = vi.spyOn(queryClient, "invalidateQueries");

    render(
      <QueryClientProvider client={queryClient}>
        <Discover />
      </QueryClientProvider>,
    );

    fireEvent.click(await screen.findByRole("button", { name: "discover.runDiscovery" }));

    await waitFor(() => expect(jobsApi.pollJobRun).toHaveBeenCalledWith(42, expect.any(Object)));
    await waitFor(() => {
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["mod-games"] });
      expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ["mod-categories"] });
    });
  });
});
