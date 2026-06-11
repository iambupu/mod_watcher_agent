// 中文注释：封装前端访问后端jobs.test接口的类型和请求函数。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { get } from "@/api/client";
import { fetchJobRuns, fetchSchedulerStatus, pollJobRun } from "@/api/jobs";
import type { JobRun } from "@/api/jobs";

vi.mock("@/api/client", () => ({
  get: vi.fn(),
  post: vi.fn(),
}));

const job = (status: JobRun["status"], id = 7): JobRun => ({
  id,
  job_name: "test_job",
  status,
  started_at: "2026-05-30T00:00:00Z",
  items_scanned: 3,
  items_matched: 2,
});

describe("pollJobRun", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reports running jobs and returns the completed job", async () => {
    vi.mocked(get)
      .mockResolvedValueOnce(job("running"))
      .mockResolvedValueOnce(job("succeeded"));
    const onRunning = vi.fn();

    const promise = pollJobRun(7, { attempts: 2, intervalMs: 1000, onRunning });
    await vi.advanceTimersByTimeAsync(2000);

    await expect(promise).resolves.toEqual({ status: "completed", job: job("succeeded") });
    expect(onRunning).toHaveBeenCalledWith(job("running"));
    expect(get).toHaveBeenCalledTimes(2);
  });

  it("can poll immediately when initialDelayMs is zero", async () => {
    vi.mocked(get).mockResolvedValue(job("succeeded"));

    const promise = pollJobRun(7, { attempts: 1, initialDelayMs: 0, intervalMs: 1000 });

    await expect(promise).resolves.toEqual({ status: "completed", job: job("succeeded") });
    expect(get).toHaveBeenCalledTimes(1);
  });

  it("stops without fetching when the run is no longer active", async () => {
    const promise = pollJobRun(7, { attempts: 1, intervalMs: 1000, isActive: () => false });
    await vi.advanceTimersByTimeAsync(1000);

    await expect(promise).resolves.toEqual({ status: "cancelled" });
    expect(get).not.toHaveBeenCalled();
  });

  it("returns timeout when all attempts remain queued or running", async () => {
    vi.mocked(get).mockResolvedValue(job("queued"));

    const promise = pollJobRun(7, { attempts: 2, intervalMs: 1000 });
    await vi.advanceTimersByTimeAsync(2000);

    await expect(promise).resolves.toEqual({ status: "timeout" });
    expect(get).toHaveBeenCalledTimes(2);
  });
});

describe("fetchJobRuns", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("clamps limit to backend bounds", async () => {
    vi.mocked(get).mockResolvedValue({ items: [] });

    await fetchJobRuns(1000);
    await fetchJobRuns(0);

    expect(get).toHaveBeenNthCalledWith(1, "/jobs/runs/recent", { limit: "200" });
    expect(get).toHaveBeenNthCalledWith(2, "/jobs/runs/recent", { limit: "1" });
  });

  it("passes dashboard metadata mode when requested", async () => {
    vi.mocked(get).mockResolvedValue({ items: [] });

    await fetchJobRuns(200, { metadata: "dashboard" });

    expect(get).toHaveBeenCalledWith("/jobs/runs/recent", { limit: "200", metadata: "dashboard" });
  });

  it("treats malformed job run lists as empty", async () => {
    vi.mocked(get).mockResolvedValue(null);

    await expect(fetchJobRuns()).resolves.toEqual({ items: [] });
  });
});

describe("fetchSchedulerStatus", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("normalizes scheduler status fields", async () => {
    vi.mocked(get).mockResolvedValue({ running: "1", jobs: undefined });

    await expect(fetchSchedulerStatus()).resolves.toEqual({ running: true, jobs: [] });
  });

  it("treats empty scheduler status responses as stopped with no jobs", async () => {
    vi.mocked(get).mockResolvedValue(null);

    await expect(fetchSchedulerStatus()).resolves.toEqual({ running: false, jobs: [] });
  });
});
