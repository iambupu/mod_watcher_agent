// 中文注释：封装前端访问后端收藏更新事件接口的类型和请求函数。

import { get, patch } from "./client";
import { nonNegativeInteger, normalizeListResponse } from "./listResponse";
import { fallbackModItem, mergeTranslatedSummary } from "./modHydration";
import { boundedIntegerParam, positiveIntegerParam } from "./params";
import { parseBoolean } from "@/utils/boolean";
import type { ModItem, UpdateEvent } from "@/types";

export interface UpdatesListParams {
  favorite_id?: number;
  seen?: boolean;
  offset?: number;
  limit?: number;
}

export interface UpdatesListResponse {
  items: UpdateEvent[];
  total: number;
}

export interface BackendUpdateEvent {
  id: number;
  mod_id: number;
  favorite_id?: number | null;
  old_version?: string | null;
  new_version?: string | null;
  old_updated_at?: string | null;
  new_updated_at?: string | null;
  raw_changelog?: string | null;
  change_summary?: string | null;
  detected_at: string;
  seen: unknown;
  translated_summary?: string | null;
  mod?: ModItem | null;
}

interface BackendUpdatesListResponse {
  items: BackendUpdateEvent[];
  total: number;
}

function buildUpdatesQuery(params?: UpdatesListParams): Record<string, string> {
  const query: Record<string, string> = {};
  if (!params) return query;
  if (params.favorite_id !== undefined) {
    const favoriteId = positiveIntegerParam(params.favorite_id);
    if (favoriteId !== undefined) query.favorite_id = favoriteId;
  }
  if (params.seen !== undefined) query.seen = String(params.seen);
  if (params.offset !== undefined) query.offset = boundedIntegerParam(params.offset, { min: 0 });
  if (params.limit !== undefined) query.limit = boundedIntegerParam(params.limit, { min: 1, max: 200 });
  return query;
}

export function hydrateUpdateEvent(event: BackendUpdateEvent): UpdateEvent {
  return {
    id: event.id,
    modId: event.mod_id,
    mod: event.mod
      ? mergeTranslatedSummary(event.mod, event.translated_summary)
      : fallbackModItem(event.mod_id, {
          firstSeenAt: event.detected_at,
          lastSeenAt: event.detected_at,
          translatedSummary: event.translated_summary,
        }),
    oldVersion: event.old_version || undefined,
    newVersion: event.new_version || undefined,
    oldUpdatedAt: event.old_updated_at || undefined,
    newUpdatedAt: event.new_updated_at || undefined,
    rawChangelog: event.raw_changelog || undefined,
    changeSummary: event.change_summary || event.translated_summary || undefined,
    detectedAt: event.detected_at,
    seen: parseBoolean(event.seen),
  };
}

export function fetchUpdates(params?: UpdatesListParams): Promise<UpdatesListResponse> {
  return get<BackendUpdatesListResponse>("/updates", buildUpdatesQuery(params)).then((data) => {
    const normalized = normalizeListResponse<BackendUpdateEvent>(data);
    return {
      items: normalized.items.map(hydrateUpdateEvent),
      total: normalized.total,
    };
  });
}

export function markUpdateSeen(eventId: number): Promise<UpdateEvent> {
  return patch<BackendUpdateEvent>(`/updates/${eventId}/seen`).then(hydrateUpdateEvent);
}

export function markAllUpdatesSeen(): Promise<{ updated: number }> {
  return patch<{ updated: number }>("/updates/seen")
    .then((data) => ({ updated: nonNegativeInteger(data?.updated) }));
}
