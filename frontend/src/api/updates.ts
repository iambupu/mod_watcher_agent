import { get, post } from "./client";
import type { UpdateEvent } from "@/types";

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

export function fetchUpdates(params?: UpdatesListParams): Promise<UpdatesListResponse> {
  return get<UpdatesListResponse>("/updates", params as unknown as Record<string, string>);
}

export function markUpdateSeen(eventId: number): Promise<UpdateEvent> {
  return post<UpdateEvent>(`/updates/${eventId}/seen`);
}

export function markAllUpdatesSeen(): Promise<void> {
  return post<void>("/updates/seen");
}
