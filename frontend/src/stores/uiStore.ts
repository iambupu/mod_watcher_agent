// 中文注释：定义 uiStore 的 Zustand 状态边界。

import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { SummaryMode } from "@/types";

interface UIState {
  sidebarOpen: boolean;
  detailDrawerOpen: boolean;
  detailDrawerModId: number | null;
  summaryMode: SummaryMode;
  settingsSyncedAt: number;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  openDetailDrawer: (modId: number) => void;
  closeDetailDrawer: () => void;
  setSummaryMode: (mode: SummaryMode) => void;
  markSettingsSynced: () => void;
}

export const useUIStore = create<UIState>()(
  persist(
    (set) => ({
      sidebarOpen: true,
      detailDrawerOpen: false,
      detailDrawerModId: null,
      summaryMode: "bilingual" as SummaryMode,
      settingsSyncedAt: 0,
      setSidebarOpen: (open) => set({ sidebarOpen: open }),
      toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
      openDetailDrawer: (modId) => set({ detailDrawerOpen: true, detailDrawerModId: modId }),
      closeDetailDrawer: () => set({ detailDrawerOpen: false, detailDrawerModId: null }),
      setSummaryMode: (mode) => set({ summaryMode: mode }),
      markSettingsSynced: () => set({ settingsSyncedAt: Date.now() }),
    }),
    {
      name: "mod-watcher-ui",
      partialize: (state) => ({
        sidebarOpen: state.sidebarOpen,
        summaryMode: state.summaryMode,
      }),
    },
  ),
);
