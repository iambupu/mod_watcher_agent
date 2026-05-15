import { useEffect, useRef } from "react";
import { fetchRecentNotifications, markNotificationsSeen, type SystemNotificationEvent } from "@/api/system-notifications";
import { fetchSettings } from "@/api/settings";

const POLL_INTERVAL_MS = 30_000;

async function showBrowserNotifications(events: SystemNotificationEvent[]): Promise<number[]> {
  const shownIds: number[] = [];
  for (const event of events) {
    try {
      const notif = new Notification(event.title, { body: event.message });
      notif.onclick = () => {
        window.focus();
        if (event.related_url) {
          window.open(event.related_url, "_blank");
        }
      };
      shownIds.push(event.id);
    } catch {
      // Browser may throttle/deny individual notifications
    }
  }
  return shownIds;
}

async function requestNotificationPermission(): Promise<void> {
  if (!("Notification" in window)) {
    return;
  }
  if (Notification.permission === "default") {
    try {
      await Notification.requestPermission();
    } catch {
      // Silently fail if browser doesn't support notifications
    }
  }
}

export function useSystemNotifications(): void {
  const sinceIdRef = useRef(0);

  useEffect(() => {
    let active = true;

    const pollAndShow = async () => {
      try {
        if (!active || !("Notification" in window)) return;
        if (Notification.permission === "default") {
          await requestNotificationPermission();
        }
        if (Notification.permission !== "granted") {
          return;
        }
        const settings = await fetchSettings();
        if (!settings.notificationsEnabled || !settings.systemNotificationsEnabled) {
          return;
        }
        const events = await fetchRecentNotifications(sinceIdRef.current);
        if (events.length === 0) return;

        const shownIds = await showBrowserNotifications(events);
        if (shownIds.length > 0) {
          await markNotificationsSeen(shownIds);
        }

        const maxId = Math.max(...events.map((e) => e.id));
        if (maxId > sinceIdRef.current) {
          sinceIdRef.current = maxId;
        }
      } catch {
        // Silently ignore polling errors
      }
    };

    pollAndShow();

    const interval = setInterval(pollAndShow, POLL_INTERVAL_MS);
    return () => {
      active = false;
      clearInterval(interval);
    };
  }, []);
}
