import { get, patch } from "./client";
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
  seen: boolean;
  translated_summary?: string | null;
  mod?: ModItem | null;
}

interface BackendUpdatesListResponse {
  items: BackendUpdateEvent[];
  total: number;
}

export function hydrateUpdateEvent(event: BackendUpdateEvent): UpdateEvent {
  return {
    id: event.id,
    modId: event.mod_id,
    mod: event.mod || {
      id: event.mod_id,
      source: "nexusmods",
      external_id: String(event.mod_id),
      game: "",
      title: `Mod #${event.mod_id}`,
      url: "",
      tags_json: "[]",
      translated_summary: event.translated_summary || undefined,
      ignored: false,
      first_seen_at: event.detected_at,
      last_seen_at: event.detected_at,
    },
    oldVersion: event.old_version || undefined,
    newVersion: event.new_version || undefined,
    oldUpdatedAt: event.old_updated_at || undefined,
    newUpdatedAt: event.new_updated_at || undefined,
    rawChangelog: event.raw_changelog || undefined,
    changeSummary: event.change_summary || event.translated_summary || undefined,
    detectedAt: event.detected_at,
    seen: event.seen,
  };
}

export function fetchUpdates(params?: UpdatesListParams): Promise<UpdatesListResponse> {
  return get<BackendUpdatesListResponse>("/updates", params as unknown as Record<string, string>).then((data) => ({
    items: data.items.map(hydrateUpdateEvent),
    total: data.total,
  }));
}

export function markUpdateSeen(eventId: number): Promise<UpdateEvent> {
  return patch<BackendUpdateEvent>(`/updates/${eventId}/seen`).then(hydrateUpdateEvent);
}

export function markAllUpdatesSeen(): Promise<{ updated: number }> {
  return patch<{ updated: number }>("/updates/seen");
}
