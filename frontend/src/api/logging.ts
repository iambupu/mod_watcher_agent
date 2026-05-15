import { get } from "./client";

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
  if (params?.limit !== undefined) query.limit = String(params.limit);
  return get<{ entries: LogEntry[] }>("/logs", query);
}
