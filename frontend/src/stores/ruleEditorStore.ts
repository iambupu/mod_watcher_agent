import { create } from "zustand";
import type {
  RuleEditorDraft,
  ModSource,
  CommonRuleFilters,
  NexusModsRuleConfig,
  LoversLabRuleConfig,
  NotificationConfig,
  WatchRule,
  WatchRuleCreate,
} from "@/types";

const EMPTY_COMMON_FILTERS: CommonRuleFilters = {};

function createEmptyDraft(): RuleEditorDraft {
  return {
    name: "",
    enabled: true,
    intervalMinutes: 360,
    commonFilters: { ...EMPTY_COMMON_FILTERS },
    nexusmodsDraft: {
      gameDomainName: "",
      updatedSinceDays: 7,
    },
    loverslabDraft: {
      gameLabel: "",
      accessMode: "rss",
      feedUrls: [],
      pageUrls: [],
      browserProfile: "loverslab",
      updatedSinceDays: 30,
      maxItemsPerRun: 50,
      updateDetection: "published_time",
    },
    notification: {
      enabled: true,
      mode: "instant",
      channels: ["desktop"],
    },
  };
}

interface RuleEditorState {
  draft: RuleEditorDraft;
  activeSource: ModSource;
  isDirty: boolean;
  editingRuleId: number | null;

  switchSource: (source: ModSource) => void;
  setBasicInfo: (patch: Partial<Pick<RuleEditorDraft, "name" | "enabled" | "intervalMinutes">>) => void;
  updateCommonFilter: (patch: Partial<CommonRuleFilters>) => void;
  updateNexusConfig: (patch: Partial<NexusModsRuleConfig>) => void;
  updateLoversLabConfig: (patch: Partial<LoversLabRuleConfig>) => void;
  updateNotification: (patch: Partial<NotificationConfig>) => void;
  loadRule: (rule: WatchRule) => void;
  resetDraft: () => void;
  getSubmitData: () => WatchRuleCreate;
}

export const useRuleEditorStore = create<RuleEditorState>((set, get) => ({
  draft: createEmptyDraft(),
  activeSource: "nexusmods",
  isDirty: false,
  editingRuleId: null,

  setBasicInfo: (patch) =>
    set((s) => ({
      draft: { ...s.draft, ...patch },
      isDirty: true,
    })),

  switchSource: (source) =>
    set((s) => ({ activeSource: source, isDirty: s.editingRuleId !== null })),

  updateCommonFilter: (patch) =>
    set((s) => ({
      draft: {
        ...s.draft,
        commonFilters: { ...s.draft.commonFilters, ...patch },
      },
      isDirty: true,
    })),

  updateNexusConfig: (patch) =>
    set((s) => ({
      draft: {
        ...s.draft,
        nexusmodsDraft: { ...s.draft.nexusmodsDraft, ...patch },
      },
      isDirty: true,
    })),

  updateLoversLabConfig: (patch) =>
    set((s) => ({
      draft: {
        ...s.draft,
        loverslabDraft: { ...s.draft.loverslabDraft, ...patch },
      },
      isDirty: true,
    })),

  updateNotification: (patch) =>
    set((s) => ({
      draft: {
        ...s.draft,
        notification: { ...s.draft.notification, ...patch },
      },
      isDirty: true,
    })),

  loadRule: (rule) => {
    const defaults = createEmptyDraft();
    const nexusmodsDraft =
      rule.source === "nexusmods"
        ? { ...defaults.nexusmodsDraft, ...(rule.sourceConfig as NexusModsRuleConfig) }
        : defaults.nexusmodsDraft;
    const loverslabDraft =
      rule.source === "loverslab"
        ? { ...defaults.loverslabDraft, ...(rule.sourceConfig as LoversLabRuleConfig) }
        : defaults.loverslabDraft;

    set({
      draft: {
        name: rule.name,
        enabled: rule.enabled,
        intervalMinutes: rule.intervalMinutes || 360,
        commonFilters: { ...defaults.commonFilters, ...rule.filters },
        nexusmodsDraft,
        loverslabDraft,
        notification: { ...defaults.notification, ...rule.notification },
      },
      activeSource: rule.source,
      isDirty: false,
      editingRuleId: rule.id,
    });
  },

  resetDraft: () =>
    set({
      draft: createEmptyDraft(),
      activeSource: "nexusmods",
      isDirty: false,
      editingRuleId: null,
    }),

  getSubmitData: () => {
    const { draft, activeSource } = get();
    const sourceConfig: NexusModsRuleConfig | LoversLabRuleConfig =
      activeSource === "nexusmods"
        ? draft.nexusmodsDraft
        : draft.loverslabDraft;
    return {
      name: draft.name,
      enabled: draft.enabled,
      intervalMinutes: draft.intervalMinutes,
      source: activeSource,
      sourceConfig,
      filters: draft.commonFilters,
      notification: draft.notification,
    };
  },
}));
