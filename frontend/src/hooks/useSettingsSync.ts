import { useEffect } from 'react';
import { getSettings } from '@/api/settings';
import { useUIStore } from '@/stores/uiStore';

const SETTINGS_SYNC_TTL_MS = 60_000;

export function useSettingsSync() {
  const setSummaryMode = useUIStore((s) => s.setSummaryMode);
  const settingsSyncedAt = useUIStore((s) => s.settingsSyncedAt);
  const markSettingsSynced = useUIStore((s) => s.markSettingsSynced);

  useEffect(() => {
    if (settingsSyncedAt > 0 && Date.now() - settingsSyncedAt < SETTINGS_SYNC_TTL_MS) {
      return;
    }
    getSettings()
      .then((settings) => {
        if (settings.summaryMode) {
          setSummaryMode(settings.summaryMode);
        }
        markSettingsSynced();
      })
      .catch(() => {
        // API failure — keep existing default
      });
  }, [markSettingsSynced, setSummaryMode, settingsSyncedAt]);
}
