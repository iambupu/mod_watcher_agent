import { useEffect, useRef } from "react";
import { dispatchWindowsNotifications, fetchRecentNotifications, markNotificationsSeen } from "@/api/system-notifications";
import { fetchSettings } from "@/api/settings";

const POLL_INTERVAL_MS = 30_000;

export function useSystemNotifications(): void {
  const sinceIdRef = useRef(0);
  const pollingRef = useRef(false);

  useEffect(() => {
    let active = true;

    const pollAndShow = async () => {
      if (pollingRef.current) {
        return;
      }
      pollingRef.current = true;
      try {
        if (!active) return;
        const settings = await fetchSettings();
        if (!active) return;
        if (!settings.notificationsEnabled || !settings.systemNotificationsEnabled) {
          return;
        }
        const events = await fetchRecentNotifications(sinceIdRef.current);
        if (!active) return;
        if (events.length === 0) return;

        const dispatchedIds = await dispatchWindowsNotifications(events);
        if (!active) return;
        if (dispatchedIds.length > 0) {
          await markNotificationsSeen(dispatchedIds);
        }
        if (!active) return;

        const maxId = Math.max(...events.map((e) => e.id));
        if (maxId > sinceIdRef.current) {
          sinceIdRef.current = maxId;
        }
      } catch {
        // Silently ignore polling errors
      } finally {
        pollingRef.current = false;
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
