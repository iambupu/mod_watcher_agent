import { get, post, patch, del } from "./client";
import type { QueuedJob } from "./jobs";
import type {
  WatchRule,
  RuleTestRequest,
  RuleTestResponse,
  NexusModsRuleConfig,
  LoversLabRuleConfig,
  CommonRuleFilters,
  NotificationConfig,
  RuleSource,
} from "@/types";

export type WatchRuleCreate = Omit<WatchRule, "id" | "createdAt" | "updatedAt">;
export type WatchRuleUpdate = Partial<WatchRuleCreate>;

interface BackendRule {
  id: number;
  name: string;
  enabled: boolean;
  intervalMinutes: number;
  source: RuleSource;
  sourceConfig: NexusModsRuleConfig | LoversLabRuleConfig;
  filters: CommonRuleFilters;
  notification: NotificationConfig;
  created_at: string;
  updated_at: string;
}

function fromBackend(r: BackendRule): WatchRule {
  return {
    id: r.id,
    name: r.name,
    enabled: r.enabled,
    intervalMinutes: r.intervalMinutes || 360,
    source: r.source,
    sourceConfig: r.sourceConfig,
    filters: r.filters,
    notification: r.notification,
    createdAt: r.created_at,
    updatedAt: r.updated_at,
  };
}

function toBackendCreate(rule: WatchRuleCreate): Record<string, unknown> {
  return {
    name: rule.name,
    enabled: rule.enabled,
    intervalMinutes: rule.intervalMinutes,
    source: rule.source,
    sourceConfig: rule.sourceConfig,
    filters: rule.filters,
    notification: rule.notification,
  };
}

function toBackendUpdate(rule: WatchRuleUpdate): Record<string, unknown> {
  const data: Record<string, unknown> = {};
  if (rule.name !== undefined) data.name = rule.name;
  if (rule.enabled !== undefined) data.enabled = rule.enabled;
  if (rule.intervalMinutes !== undefined) data.intervalMinutes = rule.intervalMinutes;
  if (rule.source !== undefined) data.source = rule.source;
  if (rule.sourceConfig !== undefined) data.sourceConfig = rule.sourceConfig;
  if (rule.filters !== undefined) data.filters = rule.filters;
  if (rule.notification !== undefined) data.notification = rule.notification;
  return data;
}

export async function fetchRules(): Promise<WatchRule[]> {
  const raw = await get<BackendRule[]>("/rules");
  return raw.map(fromBackend);
}

export async function fetchRuleById(id: number): Promise<WatchRule> {
  const raw = await get<BackendRule>(`/rules/${id}`);
  return fromBackend(raw);
}

export async function createRule(data: WatchRuleCreate): Promise<WatchRule> {
  const raw = await post<BackendRule>("/rules", toBackendCreate(data));
  return fromBackend(raw);
}

export async function updateRule(
  id: number,
  data: WatchRuleUpdate,
): Promise<WatchRule> {
  const raw = await patch<BackendRule>(`/rules/${id}`, toBackendUpdate(data));
  return fromBackend(raw);
}

export async function deleteRule(id: number): Promise<void> {
  return del<void>(`/rules/${id}`);
}

export async function toggleRule(
  id: number,
  enabled: boolean,
): Promise<WatchRule> {
  return updateRule(id, { enabled });
}

export async function runRule(id: number): Promise<QueuedJob> {
  return post<QueuedJob>(`/rules/${id}/run`);
}

export async function testRule(
  data: RuleTestRequest,
): Promise<RuleTestResponse> {
  return post<RuleTestResponse>("/rules/test", data);
}

export async function exportRules(): Promise<{ version: number; exportedAt: string; rules: WatchRuleCreate[] }> {
  return get<{ version: number; exportedAt: string; rules: WatchRuleCreate[] }>("/rules/export");
}

export async function importRulesByUrl(url: string): Promise<{ imported: number; skipped: number }> {
  return post<{ imported: number; skipped: number }>("/rules/import", { url });
}

export async function importRulesFromLocalFile(file: File): Promise<{ imported: number; skipped: number }> {
  const text = await file.text();
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    throw new Error("Invalid JSON file");
  }
  const rules = Array.isArray(parsed)
    ? parsed
    : (parsed && typeof parsed === "object" && Array.isArray((parsed as { rules?: unknown[] }).rules)
      ? (parsed as { rules: unknown[] }).rules
      : null);
  if (!rules) {
    throw new Error("JSON must be an array or an object with 'rules' array");
  }
  return post<{ imported: number; skipped: number }>("/rules/import", { rules });
}
