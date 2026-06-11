// 中文注释：封装 useSummaryRegeneration.test 相关的 React 状态同步逻辑。

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSummaryRegeneration } from "@/hooks/useSummaryRegeneration";
import { regenerateModSummary } from "@/api/mods";
import { pollJobRun, type QueuedJob } from "@/api/jobs";

vi.mock("@/api/mods", () => ({
  regenerateModSummary: vi.fn(),
}));

vi.mock("@/api/jobs", () => ({
  pollJobRun: vi.fn(),
}));

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((innerResolve) => {
    resolve = innerResolve;
  });
  return { promise, resolve };
}

type RegenerateResult = Partial<QueuedJob> & { status: string; mod_id: number; language: string };

function wrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("useSummaryRegeneration", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("keeps a mod in regenerating state until its latest regeneration finishes", async () => {
    const first = deferred<RegenerateResult>();
    const second = deferred<RegenerateResult>();
    vi.mocked(regenerateModSummary)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { result } = renderHook(
      () =>
        useSummaryRegeneration({
          t: (key) => key,
          setStatus: vi.fn(),
          primaryQueryKey: ["mods"],
        }),
      { wrapper },
    );

    act(() => {
      void result.current.regenerateSummary(42);
      void result.current.regenerateSummary(42);
    });

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.regeneratingSummaryIds.has(42)).toBe(true);

    await act(async () => {
      first.resolve({ status: "queued", mod_id: 42, language: "zh-CN" });
      await vi.advanceTimersByTimeAsync(6000);
    });

    expect(result.current.regeneratingSummaryIds.has(42)).toBe(true);

    await act(async () => {
      second.resolve({ status: "queued", mod_id: 42, language: "zh-CN" });
      await vi.advanceTimersByTimeAsync(6000);
    });

    await act(async () => {
      await Promise.resolve();
    });
    expect(result.current.regeneratingSummaryIds.has(42)).toBe(false);
  });

  it("polls queued regeneration jobs immediately with a short interval", async () => {
    vi.mocked(regenerateModSummary).mockResolvedValue({
      status: "queued",
      job_id: 7,
      mod_id: 42,
      language: "zh-CN",
    });
    vi.mocked(pollJobRun).mockResolvedValue({
      status: "completed",
      job: {
        id: 7,
        job_name: "llm_regenerate_summary",
        status: "succeeded",
        started_at: "2026-06-10T00:00:00Z",
        items_scanned: 1,
        items_matched: 1,
      },
    });

    const { result } = renderHook(
      () =>
        useSummaryRegeneration({
          t: (key) => key,
          setStatus: vi.fn(),
          primaryQueryKey: ["mods"],
        }),
      { wrapper },
    );

    await act(async () => {
      await result.current.regenerateSummary(42);
    });

    expect(pollJobRun).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        attempts: 60,
        initialDelayMs: 0,
        intervalMs: 500,
      }),
    );
  });
});
