import { create } from "zustand";
import type { SummaryMode } from "@/types";

interface UIState {
  sidebarOpen: boolean;
  detailDrawerOpen: boolean;
  detailDrawerModId: number | null;
  summaryMode: SummaryMode;
  setSidebarOpen: (open: boolean) => void;
  toggleSidebar: () => void;
  openDetailDrawer: (modId: number) => void;
  closeDetailDrawer: () => void;
  setSummaryMode: (mode: SummaryMode) => void;
}

export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  detailDrawerOpen: false,
  detailDrawerModId: null,
  summaryMode: "bilingual" as SummaryMode,
  setSidebarOpen: (open) => set({ sidebarOpen: open }),
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
  openDetailDrawer: (modId) => set({ detailDrawerOpen: true, detailDrawerModId: modId }),
  closeDetailDrawer: () => set({ detailDrawerOpen: false, detailDrawerModId: null }),
  setSummaryMode: (mode) => set({ summaryMode: mode }),
}));
