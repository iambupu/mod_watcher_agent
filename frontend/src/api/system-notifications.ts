import { get, post } from "./client";

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

export async function fetchRecentNotifications(sinceId = 0): Promise<SystemNotificationEvent[]> {
  const data = await get<RecentResponse>("/system-notifications/recent", {
    since_id: String(sinceId),
    limit: "50",
  });
  return data.events;
}

export async function markNotificationsSeen(eventIds: number[]): Promise<number> {
  const data = await post<MarkSeenResponse>("/system-notifications/mark-seen", {
    event_ids: eventIds,
  });
  return data.updated;
}
