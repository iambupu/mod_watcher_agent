import { useEffect } from 'react';
import { getSettings } from '@/api/settings';
import { useUIStore } from '@/stores/uiStore';

export function useSettingsSync() {
  const setSummaryMode = useUIStore((s) => s.setSummaryMode);
  useEffect(() => {
    getSettings()
      .then((settings) => {
        if (settings.summaryMode) {
          setSummaryMode(settings.summaryMode);
        }
      })
      .catch(() => {
        // API failure — keep existing default
      });
  }, [setSummaryMode]);
}
