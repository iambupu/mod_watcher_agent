import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { useUIStore } from '@/stores/uiStore';

vi.mock('@/api/settings', () => ({
  getSettings: vi.fn(),
}));

describe('useSettingsSync', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useUIStore.setState({ summaryMode: 'original' });
  });

  it('should fetch settings and update summaryMode in uiStore', async () => {
    const { getSettings } = await import('@/api/settings');
    (getSettings as ReturnType<typeof vi.fn>).mockResolvedValue({
      summaryMode: 'bilingual',
    });

    const { useSettingsSync } = await import('@/hooks/useSettingsSync');
    renderHook(() => useSettingsSync());

    await waitFor(() => {
      expect(getSettings).toHaveBeenCalledTimes(1);
    });

    const state = useUIStore.getState();
    expect(state.summaryMode).toBe('bilingual');
  });

  it('should handle API failure gracefully without crashing', async () => {
    const { getSettings } = await import('@/api/settings');
    (getSettings as ReturnType<typeof vi.fn>).mockRejectedValue(
      new Error('Network error')
    );

    const { useSettingsSync } = await import('@/hooks/useSettingsSync');

    expect(() => {
      renderHook(() => useSettingsSync());
    }).not.toThrow();

    await waitFor(() => {
      expect(getSettings).toHaveBeenCalledTimes(1);
    });

    const state = useUIStore.getState();
    expect(state.summaryMode).toBe('original');
  });
});
