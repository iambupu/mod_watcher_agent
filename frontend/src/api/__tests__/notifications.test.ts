// 中文注释：封装前端访问后端notifications.test接口的类型和请求函数。

import { afterEach, describe, expect, it, vi } from "vitest";

import { get, post } from "@/api/client";
import {
  fetchNotifications,
  fetchUnreadCount,
  markAllNotificationsRead,
  markNotificationsRead,
} from "@/api/notifications";
import {
  dispatchWindowsNotifications,
  fetchRecentNotifications,
  markNotificationsSeen,
  type SystemNotificationEvent,
} from "@/api/system-notifications";

vi.mock("@/api/client", () => ({
  get: vi.fn(),
  post: vi.fn(),
}));

describe("notifications API", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("clamps notification pagination params to backend bounds", async () => {
    vi.mocked(get).mockResolvedValue({ items: [], total: 0 });

    await fetchNotifications(-5, 500);

    expect(get).toHaveBeenCalledWith("/notifications", {
      offset: "0",
      limit: "200",
    });
  });

  it("normalizes malformed notification list responses", async () => {
    vi.mocked(get).mockResolvedValue({ items: undefined, total: "bad" });

    await expect(fetchNotifications()).resolves.toEqual({ items: [], total: 0 });
  });

  it("does not post empty notification read batches", async () => {
    await expect(markNotificationsRead([])).resolves.toEqual({ updated: 0 });

    expect(post).not.toHaveBeenCalled();
  });

  it("filters invalid notification read ids", async () => {
    vi.mocked(post).mockResolvedValue({ updated: "2.9" });

    await expect(markNotificationsRead([1, 0, -1, Number.NaN, 2])).resolves.toEqual({ updated: 2 });

    expect(post).toHaveBeenCalledWith("/notifications/mark-read", {
      ids: [1, 2],
    });
  });

  it("does not post notification read batches without valid ids", async () => {
    await expect(markNotificationsRead([0, -1, Number.NaN])).resolves.toEqual({ updated: 0 });

    expect(post).not.toHaveBeenCalled();
  });

  it("normalizes notification count responses", async () => {
    vi.mocked(post).mockResolvedValue(null);
    vi.mocked(get).mockResolvedValue(null);

    await expect(markAllNotificationsRead()).resolves.toEqual({ updated: 0 });
    await expect(fetchUnreadCount()).resolves.toEqual({ count: 0 });
  });
});

describe("system notifications API", () => {
  afterEach(() => {
    vi.clearAllMocks();
  });

  it("clamps recent notification since id", async () => {
    vi.mocked(get).mockResolvedValue({ events: [] });

    await fetchRecentNotifications(-2);

    expect(get).toHaveBeenCalledWith("/system-notifications/recent", {
      since_id: "0",
      limit: "50",
    });
  });

  it("filters malformed recent system notification events", async () => {
    vi.mocked(get).mockResolvedValue({
      events: [
        {
          id: 3,
          event_type: "job_failed",
          title: "Failed",
          message: "Job failed",
          mod_id: null,
          related_url: null,
          seen: false,
          created_at: "2026-05-30T00:00:00Z",
        },
        { id: Number.NaN, title: "bad" },
        {
          id: 4,
          event_type: "missing_seen",
          title: "Bad",
          message: "Bad event",
          created_at: "2026-05-30T00:00:00Z",
        },
      ],
    });

    await expect(fetchRecentNotifications(2)).resolves.toEqual([
      {
        id: 3,
        event_type: "job_failed",
        title: "Failed",
        message: "Job failed",
        mod_id: null,
        related_url: null,
        seen: false,
        created_at: "2026-05-30T00:00:00Z",
      },
    ]);
  });

  it("treats empty recent system notification responses as empty", async () => {
    vi.mocked(get).mockResolvedValue(null);

    await expect(fetchRecentNotifications(2)).resolves.toEqual([]);
  });

  it("does not post empty seen or dispatch batches", async () => {
    await expect(markNotificationsSeen([])).resolves.toBe(0);
    await expect(dispatchWindowsNotifications([])).resolves.toEqual([]);

    expect(post).not.toHaveBeenCalled();
  });

  it("filters invalid system notification event ids", async () => {
    vi.mocked(post)
      .mockResolvedValueOnce({ updated: "2.9" })
      .mockResolvedValueOnce({ dispatched_ids: [1, -2, Number.NaN, 3] });

    await expect(markNotificationsSeen([1, 0, -1, Number.NaN, 2])).resolves.toBe(2);
    await expect(dispatchWindowsNotifications([
      { id: 1 } as SystemNotificationEvent,
      { id: 0 } as SystemNotificationEvent,
      { id: Number.NaN } as SystemNotificationEvent,
      { id: 3 } as SystemNotificationEvent,
    ])).resolves.toEqual([1, 3]);

    expect(post).toHaveBeenNthCalledWith(1, "/system-notifications/mark-seen", {
      event_ids: [1, 2],
    });
    expect(post).toHaveBeenNthCalledWith(2, "/system-notifications/dispatch-windows", {
      event_ids: [1, 3],
    });
  });

  it("caps windows dispatch batches to backend bounds", async () => {
    vi.mocked(post).mockResolvedValue({ dispatched_ids: [] });
    const events = Array.from({ length: 55 }, (_, index) => ({ id: index + 1 }) as SystemNotificationEvent);

    await dispatchWindowsNotifications(events);

    expect(post).toHaveBeenCalledWith("/system-notifications/dispatch-windows", {
      event_ids: Array.from({ length: 50 }, (_, index) => index + 1),
    });
  });

  it("treats malformed dispatch response ids as empty", async () => {
    vi.mocked(post).mockResolvedValue(null);

    await expect(dispatchWindowsNotifications([{ id: 1 } as SystemNotificationEvent])).resolves.toEqual([]);
  });
});
