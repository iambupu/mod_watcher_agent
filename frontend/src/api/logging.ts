import { get, post } from "./client";
import { boundedIntegerParam } from "./params";
import { arrayOrEmpty } from "@/utils/array";

export interface LogEntry {
  time: string;
  timestamp?: string;
  level: string;
  module?: string;
  name?: string;
  message: string;
}

export function fetchLogs(params?: {
  level?: string;
  search?: string;
  limit?: number;
}): Promise<{ entries: LogEntry[] }> {
  const query: Record<string, string> = {};
  if (params?.level) query.level = params.level;
  if (params?.search) query.search = params.search;
  if (params?.limit !== undefined) query.limit = boundedIntegerParam(params.limit, { min: 1, max: 1000 });
  return get<{ entries: LogEntry[] }>("/logs", query).then((data) => ({
    entries: arrayOrEmpty<LogEntry>(data?.entries),
  }));
}

export function openLogDirectory(): Promise<{ opened: boolean; path: string }> {
  return post<{ opened: boolean; path: string }>("/logs/open-dir");
}
