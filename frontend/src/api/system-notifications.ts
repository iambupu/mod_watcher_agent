import { get, post } from "./client";
import { nonNegativeInteger } from "./listResponse";
import { boundedIntegerParam } from "./params";
import { positiveIntegerIds } from "@/utils/ids";

const MAX_WINDOWS_DISPATCH_BATCH = 50;

export interface SystemNotificationEvent {
  id: number;
  event_type: string;
  title: string;
  message: string;
  mod_id: number | null;
  related_url: string | null;
  seen: boolean;
  created_at: string;
}

interface RecentResponse {
  events: SystemNotificationEvent[];
}

interface MarkSeenResponse {
  updated: number;
}

interface DispatchWindowsResponse {
  dispatched_ids: number[];
}

export async function fetchRecentNotifications(sinceId = 0): Promise<SystemNotificationEvent[]> {
  const data = await get<RecentResponse>("/system-notifications/recent", {
    since_id: boundedIntegerParam(sinceId, { min: 0 }),
    limit: "50",
  });
  return Array.isArray(data?.events) ? data.events.filter(isSystemNotificationEvent) : [];
}

export async function markNotificationsSeen(eventIds: number[]): Promise<number> {
  const validIds = positiveIntegerIds(eventIds);
  if (validIds.length === 0) {
    return 0;
  }
  const data = await post<MarkSeenResponse>("/system-notifications/mark-seen", {
    event_ids: validIds,
  });
  return nonNegativeInteger(data?.updated);
}

export async function dispatchWindowsNotifications(
  events: SystemNotificationEvent[],
): Promise<number[]> {
  if (events.length === 0) {
    return [];
  }
  const eventIds = positiveIntegerIds(events.map((e) => e.id)).slice(0, MAX_WINDOWS_DISPATCH_BATCH);
  if (eventIds.length === 0) {
    return [];
  }
  const data = await post<DispatchWindowsResponse>("/system-notifications/dispatch-windows", {
    event_ids: eventIds,
  });
  return positiveIntegerIds(data?.dispatched_ids);
}

function isSystemNotificationEvent(value: unknown): value is SystemNotificationEvent {
  if (!value || typeof value !== "object") {
    return false;
  }
  const event = value as Partial<SystemNotificationEvent>;
  return (
    typeof event.id === "number"
    && Number.isInteger(event.id)
    && event.id > 0
    && typeof event.event_type === "string"
    && typeof event.title === "string"
    && typeof event.message === "string"
    && typeof event.seen === "boolean"
    && typeof event.created_at === "string"
  );
}
