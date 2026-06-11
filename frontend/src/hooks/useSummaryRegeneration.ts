// 中文注释：封装 useSummaryRegeneration 相关的 React 状态同步逻辑。

import { useEffect, useRef, useState } from "react";
import { useMutation, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { pollJobRun } from "@/api/jobs";
import { regenerateModSummary } from "@/api/mods";

type Translate = (key: string, options?: Record<string, unknown>) => string;

interface UseSummaryRegenerationOptions {
  t: Translate;
  setStatus: (message: string) => void;
  primaryQueryKey: QueryKey;
  extraQueryKeys?: QueryKey[];
  refetch?: () => unknown | Promise<unknown>;
}

const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export function useSummaryRegeneration({
  t,
  setStatus,
  primaryQueryKey,
  extraQueryKeys = [],
  refetch,
}: UseSummaryRegenerationOptions) {
  const queryClient = useQueryClient();
  const mountedRef = useRef(true);
  const runSequenceRef = useRef(0);
  const runTokensRef = useRef<Map<number, number>>(new Map());
  const [regeneratingSummaryIds, setRegeneratingSummaryIds] = useState<Set<number>>(new Set());
  const regenerateSummaryMutation = useMutation({
    mutationFn: regenerateModSummary,
  });

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      runTokensRef.current.clear();
    };
  }, []);

  const invalidate = async (includeExtras: boolean) => {
    await queryClient.invalidateQueries({ queryKey: primaryQueryKey });
    if (includeExtras) {
      for (const queryKey of extraQueryKeys) {
        await queryClient.invalidateQueries({ queryKey });
      }
    }
    await refetch?.();
  };

  const regenerateSummary = async (modId: number) => {
    const runToken = runSequenceRef.current + 1;
    runSequenceRef.current = runToken;
    runTokensRef.current.set(modId, runToken);
    const isActive = () => mountedRef.current && runTokensRef.current.get(modId) === runToken;
    setRegeneratingSummaryIds((prev) => {
      const next = new Set(prev);
      next.add(modId);
      return next;
    });

    try {
      const result = await regenerateSummaryMutation.mutateAsync(modId);
      if (!isActive()) return;

      if (typeof result.job_id !== "number") {
        setStatus(t("mod.summaryRegenerateQueuedNoJob"));
        await delay(6000);
        if (!isActive()) return;
        await invalidate(true);
        return;
      }

      setStatus(t("mod.summaryRegenerateQueued", { jobId: result.job_id }));
      const pollResult = await pollJobRun(result.job_id, {
        attempts: 60,
        initialDelayMs: 0,
        intervalMs: 500,
        isActive,
        onRunning: (job) => {
          setStatus(t("mod.summaryRegenerateRunning", { jobId: result.job_id, status: t(`jobs.status.${job.status}`) }));
        },
      });
      if (pollResult.status === "cancelled") return;
      if (pollResult.status === "timeout") {
        setStatus(t("mod.summaryRegenerateTimeout"));
        await invalidate(false);
        return;
      }
      const job = pollResult.job;
      if (job.status === "failed") {
        setStatus(t("mod.summaryRegenerateFailed", { error: job.error_message || t("jobs.failedDefault") }));
        return;
      }

      setStatus(t("mod.summaryRegenerateDone", { jobId: result.job_id }));
      await invalidate(true);
    } catch (error) {
      if (isActive()) {
        setStatus(t("mod.summaryRegenerateFailed", { error: error instanceof Error ? error.message : t("common.unknown") }));
      }
    } finally {
      if (isActive()) {
        runTokensRef.current.delete(modId);
        setRegeneratingSummaryIds((prev) => {
          const next = new Set(prev);
          next.delete(modId);
          return next;
        });
      }
    }
  };

  return {
    regenerateSummary,
    regeneratingSummaryIds,
  };
}
