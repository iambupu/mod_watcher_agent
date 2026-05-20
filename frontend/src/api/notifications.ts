import { get, post } from "./client";
import type { NotificationList } from "@/types";

export function fetchNotifications(offset = 0, limit = 30): Promise<NotificationList> {
  return get<NotificationList>("/notifications", {
    offset: String(offset),
    limit: String(limit),
  });
}

export function markNotificationsRead(ids: number[]): Promise<{ updated: number }> {
  return post<{ updated: number }>("/notifications/mark-read", { ids });
}

export function markAllNotificationsRead(): Promise<{ updated: number }> {
  return post<{ updated: number }>("/notifications/mark-all-read");
}

export function fetchUnreadCount(): Promise<{ count: number }> {
  return get<{ count: number }>("/notifications/unread-count");
}
