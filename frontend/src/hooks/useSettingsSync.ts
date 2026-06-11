// 中文注释：封装 useSettingsSync 相关的 React 状态同步逻辑。

import { useEffect } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { useUIStore } from '@/stores/uiStore';

const SETTINGS_SYNC_TTL_MS = 60_000;

async function fetchSettingsForSync() {
  const { fetchSettings } = await import('@/api/settings');
  return fetchSettings();
}

export function useSettingsSync() {
  const queryClient = useQueryClient();
  const setSummaryMode = useUIStore((s) => s.setSummaryMode);
  const settingsSyncedAt = useUIStore((s) => s.settingsSyncedAt);
  const markSettingsSynced = useUIStore((s) => s.markSettingsSynced);

  useEffect(() => {
    if (settingsSyncedAt > 0 && Date.now() - settingsSyncedAt < SETTINGS_SYNC_TTL_MS) {
      return;
    }
    queryClient.fetchQuery({
      queryKey: ["settings"],
      queryFn: fetchSettingsForSync,
      staleTime: SETTINGS_SYNC_TTL_MS,
    })
      .then((settings) => {
        if (settings.summaryMode) {
          setSummaryMode(settings.summaryMode);
        }
        markSettingsSynced();
      })
      .catch(() => {
        // API failure — keep existing default
      });
  }, [markSettingsSynced, queryClient, setSummaryMode, settingsSyncedAt]);
}
