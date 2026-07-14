import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { addFavorite, removeFavorite } from "@/api/favorites";
import { useFavoriteToggle } from "@/hooks/useFavoriteToggle";

vi.mock("@/api/favorites", () => ({
  addFavorite: vi.fn(),
  removeFavorite: vi.fn(),
}));

const queryClient = new QueryClient({
  defaultOptions: { mutations: { retry: false }, queries: { retry: false } },
});

function wrapper({ children }: { children: React.ReactNode }) {
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useFavoriteToggle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient.clear();
  });

  it("adds an unfavorited mod and invalidates configured queries", async () => {
    vi.mocked(addFavorite).mockResolvedValue({} as never);
    const invalidate = vi.spyOn(queryClient, "invalidateQueries");
    const { result } = renderHook(
      () =>
        useFavoriteToggle({
          favoriteByModId: new Map(),
          invalidateQueryKeys: [["favorites"], ["stats"]],
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.toggleFavorite(42);
    });

    expect(addFavorite).toHaveBeenCalledWith({ mod_id: 42 });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["favorites"] });
    expect(invalidate).toHaveBeenCalledWith({ queryKey: ["stats"] });
  });

  it("removes the existing favorite", async () => {
    vi.mocked(removeFavorite).mockResolvedValue(undefined);
    const { result } = renderHook(
      () =>
        useFavoriteToggle({
          favoriteByModId: new Map([[42, { id: 7, modId: 42 }]]),
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.toggleFavorite(42);
    });

    expect(removeFavorite).toHaveBeenCalledWith(7);
  });
});
