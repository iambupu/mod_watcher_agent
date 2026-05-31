import { get, post } from "./client";
import { nonNegativeInteger, normalizeListResponse } from "./listResponse";
import { boundedIntegerParam } from "./params";
import type { NotificationList } from "@/types";
import { positiveIntegerIds } from "@/utils/ids";

export function fetchNotifications(offset = 0, limit = 30): Promise<NotificationList> {
  return get<NotificationList>("/notifications", {
    offset: boundedIntegerParam(offset, { min: 0 }),
    limit: boundedIntegerParam(limit, { min: 1, max: 200 }),
  }).then(normalizeListResponse);
}

export function markNotificationsRead(ids: number[]): Promise<{ updated: number }> {
  const validIds = positiveIntegerIds(ids);
  if (validIds.length === 0) {
    return Promise.resolve({ updated: 0 });
  }
  return post<{ updated: number }>("/notifications/mark-read", { ids: validIds })
    .then((data) => ({ updated: nonNegativeInteger(data?.updated) }));
}

export function markAllNotificationsRead(): Promise<{ updated: number }> {
  return post<{ updated: number }>("/notifications/mark-all-read")
    .then((data) => ({ updated: nonNegativeInteger(data?.updated) }));
}

export function fetchUnreadCount(): Promise<{ count: number }> {
  return get<{ count: number }>("/notifications/unread-count")
    .then((data) => ({ count: nonNegativeInteger(data?.count) }));
}
