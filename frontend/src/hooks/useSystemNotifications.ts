// 中文注释：封装 useSystemNotifications 相关的 React 状态同步逻辑。

import { useEffect, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";

const POLL_INTERVAL_MS = 30_000;
const SETTINGS_STALE_MS = POLL_INTERVAL_MS - 1;

async function fetchSettingsForNotifications() {
  const { fetchSettings } = await import("@/api/settings");
  return fetchSettings();
}

async function loadSystemNotificationsApi() {
  return import("@/api/system-notifications");
}

export function useSystemNotifications(): void {
  const queryClient = useQueryClient();
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
        const settings = await queryClient.fetchQuery({
          queryKey: ["settings"],
          queryFn: fetchSettingsForNotifications,
          staleTime: SETTINGS_STALE_MS,
        });
        if (!active) return;
        if (!settings.notificationsEnabled || !settings.systemNotificationsEnabled) {
          return;
        }
        const { dispatchWindowsNotifications, fetchRecentNotifications, markNotificationsSeen } =
          await loadSystemNotificationsApi();
        if (!active) return;
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
  }, [queryClient]);
}
