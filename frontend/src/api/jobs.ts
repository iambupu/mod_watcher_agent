import { get, post } from "./client";
import { boundedIntegerParam } from "./params";
import { arrayOrEmpty } from "@/utils/array";
import { parseBoolean } from "@/utils/boolean";

export interface QueuedJob {
  status: "queued";
  job_id: number;
}

export interface JobRun {
  id: number;
  job_name: string;
  status: "queued" | "running" | "succeeded" | "failed";
  started_at: string;
  finished_at?: string | null;
  items_scanned: number;
  items_matched: number;
  error_message?: string | null;
  metadata_json?: string | null;
}

export interface SummaryReportResult {
  generated: boolean;
  reason?: string;
  provider?: string;
  model?: string;
  report?: string;
  window_minutes?: number;
  items_scanned: number;
  items_matched: number;
}

export interface JobRunList {
  items: JobRun[];
}

export type PollJobRunResult =
  | { status: "completed"; job: JobRun }
  | { status: "cancelled" }
  | { status: "timeout" };

export interface PollJobRunOptions {
  attempts?: number;
  intervalMs?: number;
  isActive?: () => boolean;
  onRunning?: (job: JobRun) => void;
}

export interface SchedulerJob {
  id: string;
  name: string;
  next_run_time?: string | null;
}

export interface SchedulerStatus {
  running: boolean;
  state?: number;
  jobs: SchedulerJob[];
}

export interface SchedulerControlResult {
  running: boolean;
  state?: number;
}

export function runSummaryReport(): Promise<SummaryReportResult> {
  return post<SummaryReportResult>("/jobs/summary-report/run");
}

export function runDiscoveryAll(): Promise<QueuedJob> {
  return post<QueuedJob>("/jobs/discover-all");
}

export function importNexusModsGame(payload: {
  gameDomainName: string;
  batchSize?: number;
  maxBatches?: number;
}): Promise<QueuedJob> {
  return post<QueuedJob>("/jobs/nexusmods/import-game", {
    game_domain_name: payload.gameDomainName,
    batch_size: payload.batchSize,
    max_batches: payload.maxBatches,
  });
}

export function runFavoriteCheck(): Promise<QueuedJob> {
  return post<QueuedJob>("/jobs/check-favorites");
}

export function fetchJobRun(jobId: number): Promise<JobRun> {
  return get<JobRun>(`/jobs/${jobId}`);
}

const delay = (ms: number) => new Promise((resolve) => window.setTimeout(resolve, ms));

export async function pollJobRun(jobId: number, options: PollJobRunOptions = {}): Promise<PollJobRunResult> {
  const attempts = options.attempts ?? 60;
  const intervalMs = options.intervalMs ?? 2000;
  const isActive = options.isActive ?? (() => true);

  for (let i = 0; i < attempts; i += 1) {
    await delay(intervalMs);
    if (!isActive()) return { status: "cancelled" };
    const job = await fetchJobRun(jobId);
    if (!isActive()) return { status: "cancelled" };
    if (job.status === "queued" || job.status === "running") {
      options.onRunning?.(job);
      continue;
    }
    return { status: "completed", job };
  }

  return { status: "timeout" };
}

export function fetchJobRuns(limit = 50): Promise<JobRunList> {
  return get<JobRunList>("/jobs/runs/recent", { limit: boundedIntegerParam(limit, { min: 1, max: 200 }) })
    .then((data) => ({ items: arrayOrEmpty<JobRun>(data?.items) }));
}

export function fetchSchedulerStatus(): Promise<SchedulerStatus> {
  return get<SchedulerStatus>("/jobs/status").then((data) => ({
    ...data,
    running: parseBoolean(data?.running),
    jobs: arrayOrEmpty<SchedulerJob>(data?.jobs),
  }));
}

export function pauseScheduler(): Promise<SchedulerControlResult> {
  return post<SchedulerControlResult>("/jobs/pause");
}

export function resumeScheduler(): Promise<SchedulerControlResult> {
  return post<SchedulerControlResult>("/jobs/resume");
}
