import { useEffect, useRef } from "react";
import { dispatchWindowsNotifications, fetchRecentNotifications, markNotificationsSeen } from "@/api/system-notifications";
import { fetchSettings } from "@/api/settings";

const POLL_INTERVAL_MS = 30_000;

export function useSystemNotifications(): void {
  const sinceIdRef = useRef(0);

  useEffect(() => {
    let active = true;

    const pollAndShow = async () => {
      try {
        if (!active) return;
        const settings = await fetchSettings();
        if (!settings.notificationsEnabled || !settings.systemNotificationsEnabled) {
          return;
        }
        const events = await fetchRecentNotifications(sinceIdRef.current);
        if (events.length === 0) return;

        const dispatchedIds = await dispatchWindowsNotifications(events);
        if (dispatchedIds.length > 0) {
          await markNotificationsSeen(dispatchedIds);
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
