import { describe, it, expect, beforeEach } from 'vitest';
import { act } from '@testing-library/react';
import { useUIStore } from '../uiStore';

describe('uiStore', () => {
  beforeEach(() => {
    useUIStore.setState({
      sidebarOpen: true,
      detailDrawerOpen: false,
      detailDrawerModId: null,
      summaryMode: 'original',
    });
  });

  it('should have summaryMode default to "original"', () => {
    const state = useUIStore.getState();
    expect(state.summaryMode).toBe('original');
  });

  it('should update summaryMode via setSummaryMode', () => {
    act(() => {
      useUIStore.getState().setSummaryMode('bilingual');
    });
    expect(useUIStore.getState().summaryMode).toBe('bilingual');
  });

  it('should accept "original" | "translated" | "bilingual" as valid summaryMode values', () => {
    const validModes = ['original', 'translated', 'bilingual'] as const;

    validModes.forEach((mode) => {
      act(() => {
        useUIStore.getState().setSummaryMode(mode);
      });
      expect(useUIStore.getState().summaryMode).toBe(mode);
    });
  });
});
