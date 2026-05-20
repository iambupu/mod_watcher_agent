import { get, post } from "./client";

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

export interface SchedulerJob {
  id: string;
  name: string;
  next_run_time?: string | null;
}

export interface SchedulerStatus {
  running: boolean;
  jobs: SchedulerJob[];
}

export interface JobLog {
  id: number;
  channel: string;
  subject: string;
  status: string;
  created_at: string;
  sent_at?: string;
}

export function fetchJobLogs(): Promise<JobLog[]> {
  return get<JobLog[]>("/jobs");
}

export function queueSummaryGeneration(): Promise<{ status: string }> {
  return post<{ status: string }>("/jobs/generate-summaries");
}

export function runSummaryGeneration(): Promise<QueuedJob> {
  return post<QueuedJob>("/jobs/generate-summaries/run");
}

export function runSummaryReport(): Promise<SummaryReportResult> {
  return post<SummaryReportResult>("/jobs/summary-report/run");
}

export function runDiscoveryAll(): Promise<QueuedJob> {
  return post<QueuedJob>("/jobs/discover-all");
}

export function runFavoriteCheck(): Promise<QueuedJob> {
  return post<QueuedJob>("/jobs/check-favorites");
}

export function fetchJobRun(jobId: number): Promise<JobRun> {
  return get<JobRun>(`/jobs/${jobId}`);
}

export function fetchJobRuns(limit = 50): Promise<JobRunList> {
  return get<JobRunList>("/jobs/runs/recent", { limit: String(limit) });
}

export function fetchSchedulerStatus(): Promise<SchedulerStatus> {
  return get<SchedulerStatus>("/jobs/status");
}
