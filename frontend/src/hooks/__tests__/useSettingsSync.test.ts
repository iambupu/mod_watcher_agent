import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useUIStore } from '@/stores/uiStore';

vi.mock('@/api/settings', () => ({
  fetchSettings: vi.fn(),
}));

describe('useSettingsSync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ summaryMode: 'original', settingsSyncedAt: 0 });
  });

  it('should fetch settings and update summaryMode in uiStore', async () => {
    const { fetchSettings } = await import('@/api/settings');
    (fetchSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      summaryMode: 'bilingual',
    });

    const { useSettingsSync } = await import('@/hooks/useSettingsSync');
    renderHook(() => useSettingsSync());

    await waitFor(() => {
      expect(fetchSettings).toHaveBeenCalledTimes(1);
    });

    const state = useUIStore.getState();
    expect(state.summaryMode).toBe('bilingual');
  });

  it('should handle API failure gracefully without crashing', async () => {
    const { fetchSettings } = await import('@/api/settings');
    (fetchSettings as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Network error')
    );

    const { useSettingsSync } = await import('@/hooks/useSettingsSync');

    expect(() => {
      renderHook(() => useSettingsSync());
    }).not.toThrow();

    await waitFor(() => {
      expect(fetchSettings).toHaveBeenCalledTimes(1);
    });

    const state = useUIStore.getState();
    expect(state.summaryMode).toBe('original');
  });

  it('should not fetch settings again within sync ttl', async () => {
    const { fetchSettings } = await import('@/api/settings');
    (fetchSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      summaryMode: 'translated',
    });

    const { useSettingsSync } = await import('@/hooks/useSettingsSync');
    renderHook(() => useSettingsSync());
    await waitFor(() => {
      expect(fetchSettings).toHaveBeenCalledTimes(1);
    });

    renderHook(() => useSettingsSync());
    await waitFor(() => {
      expect(useUIStore.getState().settingsSyncedAt).toBeGreaterThan(0);
    });
    expect(fetchSettings).toHaveBeenCalledTimes(1);
  });
});
