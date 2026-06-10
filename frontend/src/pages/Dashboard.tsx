import React from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BellRing,
  Bot,
  ChevronLeft,
  ChevronRight,
  Clock,
  Database,
  Download,
  Heart,
  LayoutDashboard,
  MessageCircle,
  Pause,
  Play,
  RefreshCw,
  SlidersHorizontal,
  Sparkles,
  ThumbsUp,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import AppSidebar from "@/components/layout/AppSidebar";
import { MarkdownText } from "@/components/MarkdownText";
import { SourceBadge } from "@/components/SourceBadge";
import { Panel } from "@/components/ui/Panel";
import { fetchStats } from "@/api/stats";
import type { Stats } from "@/api/stats";
import { fetchRecommendedMods } from "@/api/mods";
import { addFavorite, favoriteByModId as mapFavoritesByModId, fetchFavoriteRefs, removeFavorite } from "@/api/favorites";
import { fetchJobRuns, fetchSchedulerStatus, pauseScheduler, resumeScheduler, runSummaryReport } from "@/api/jobs";
import type { JobRun } from "@/api/jobs";
import { fetchSettings } from "@/api/settings";
import { useUIStore } from "@/stores/uiStore";
import { parseJobMetadata } from "@/utils/jobMetadata";
import { isAdultContent } from "@/utils/modAdult";
import { formatModTitle } from "@/utils/modTitle";
import { nonNegativeNumberValue } from "@/utils/numberInput";
import type { ModItem } from "@/types";
import { ModalHeader, ModalShell } from "@/components/ui/Modal";
import { FilterBarButton } from "@/components/ui/FilterControls";

interface StatCardConfig {
  icon: React.ReactNode;
  labelKey: string;
  valueKey: keyof Stats;
  tone: "blue" | "green" | "red" | "purple" | "orange";
  noteKey: string;
}

const STAT_CARDS: StatCardConfig[] = [
  {
    icon: <LayoutDashboard size={24} />,
    labelKey: "dashboard.totalMods",
    valueKey: "total_mods",
    tone: "blue",
    noteKey: "dashboard.statNote.totalMods",
  },
  {
    icon: <TrendingUp size={24} />,
    labelKey: "dashboard.newModsThisWeek",
    valueKey: "new_mods_this_week",
    tone: "green",
    noteKey: "dashboard.statNote.newModsThisWeek",
  },
  {
    icon: <Heart size={24} />,
    labelKey: "dashboard.totalFavorites",
    valueKey: "total_favorites",
    tone: "red",
    noteKey: "dashboard.statNote.totalFavorites",
  },
  {
    icon: <SlidersHorizontal size={24} />,
    labelKey: "dashboard.watchRules",
    valueKey: "total_rules",
    tone: "purple",
    noteKey: "dashboard.statNote.watchRules",
  },
  {
    icon: <BellRing size={24} />,
    labelKey: "dashboard.unseenUpdates",
    valueKey: "unseen_updates",
    tone: "orange",
    noteKey: "dashboard.statNote.unseenUpdates",
  },
];

const toneClasses = {
  blue: {
    icon: "bg-blue-50 text-blue-600",
    delta: "text-blue-600",
  },
  green: {
    icon: "bg-emerald-50 text-emerald-600",
    delta: "text-emerald-600",
  },
  red: {
    icon: "bg-rose-50 text-rose-600",
    delta: "text-rose-600",
  },
  purple: {
    icon: "bg-purple-50 text-purple-600",
    delta: "text-purple-600",
  },
  orange: {
    icon: "bg-orange-50 text-orange-600",
    delta: "text-orange-600",
  },
};

function compactNumber(value?: unknown): string {
  const parsed = nonNegativeNumberValue(value);
  if (parsed === null) return "0";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(parsed);
}

function formatTime(value?: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function formatDateTime(value: Date): string {
  return value.toLocaleString(undefined, {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function jobStatusClass(status: JobRun["status"]): string {
  if (status === "succeeded") return "bg-emerald-50 text-emerald-700";
  if (status === "running") return "bg-blue-50 text-blue-700";
  if (status === "queued") return "bg-slate-100 text-slate-600";
  return "bg-rose-50 text-rose-700";
}

function getJobDisplayName(job: JobRun): string {
  const ruleName = parseJobMetadata(job.metadata_json).rule_name;
  return typeof ruleName === "string" && ruleName.trim() ? ruleName : job.job_name;
}

function getLatestSummaryJob(jobs: JobRun[]): JobRun | undefined {
  return jobs.find((job) => job.job_name === "llm_summary_report");
}

function getLatestSummaryReportJob(jobs: JobRun[]): JobRun | undefined {
  for (const job of jobs) {
    if (job.job_name !== "llm_summary_report") continue;
    const report = parseJobMetadata(job.metadata_json).report;
    if (typeof report === "string" && report.trim()) return job;
  }
  return undefined;
}

const StatCard: React.FC<{ config: StatCardConfig; value?: number; loading?: boolean }> = ({
  config,
  value,
  loading,
}) => {
  const { t } = useTranslation();
  const tone = toneClasses[config.tone];

  return (
    <Panel padding="lg">
      <div className="flex items-center gap-4">
        <div className={`flex h-16 w-16 items-center justify-center rounded-xl ${tone.icon}`}>
          {loading ? <div className="h-6 w-6 animate-pulse rounded bg-slate-200" /> : config.icon}
        </div>
        <div className="min-w-0">
          <p className="text-sm font-semibold text-slate-500">{t(config.labelKey)}</p>
          <p className="mt-1 text-3xl font-bold text-slate-950">{loading ? "--" : value ?? 0}</p>
          <p className="mt-1 text-xs font-semibold text-slate-400">
            <span className={tone.delta}>{t(config.noteKey)}</span>
          </p>
        </div>
      </div>
    </Panel>
  );
};

const RecommendedModCard: React.FC<{
  mod: ModItem;
  isFavorited: boolean;
  onToggleFavorite: (modId: number) => void;
}> = ({ mod, isFavorited, onToggleFavorite }) => {
  const summaryMode = useUIStore((s) => s.summaryMode);
  const displayTitle = formatModTitle(mod, summaryMode);
  return (
    <Panel
      as="div"
      padding="none"
      className="group w-[220px] shrink-0 overflow-hidden transition hover:-translate-y-0.5 hover:border-blue-200 hover:shadow-md"
    >
      <div className="aspect-[4/3] overflow-hidden bg-slate-100">
        <div className="relative h-full w-full">
          <a href={mod.url} target="_blank" rel="noopener noreferrer" className="block h-full w-full">
            {mod.thumbnail_url ? (
              <img src={mod.thumbnail_url} alt={displayTitle} className="h-full w-full object-cover" loading="lazy" />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-slate-300">
                <Sparkles size={32} />
              </div>
            )}
          </a>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              onToggleFavorite(mod.id);
            }}
            className="absolute right-2 top-2 rounded-full bg-white/90 p-2 text-slate-400 shadow-sm transition hover:bg-white hover:text-rose-500"
            aria-label={isFavorited ? "Unfavorite" : "Favorite"}
          >
            <Heart size={16} className={isFavorited ? "fill-rose-500 text-rose-500" : ""} />
          </button>
        </div>
      </div>
      <div className="space-y-2 p-3">
        <a href={mod.url} target="_blank" rel="noopener noreferrer" className="block">
          <h4 className="line-clamp-2 min-h-10 whitespace-pre-line text-sm font-bold leading-5 text-slate-900 group-hover:text-blue-700">
            {displayTitle}
          </h4>
        </a>
        <p className="truncate text-xs font-semibold text-slate-500">{mod.game || mod.game_domain || "-"}</p>
        <div className="flex flex-wrap items-center gap-1.5">
          <SourceBadge source={mod.source} />
          {isAdultContent(mod.adult_content) && (
            <span className="inline-flex items-center rounded-md border border-rose-200 bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-700">
              NSFW
            </span>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs font-semibold text-slate-400">
          <span className="inline-flex items-center gap-1">
            <Download size={12} />
            {compactNumber(mod.downloads)}
          </span>
          <span className="inline-flex items-center gap-1">
            <ThumbsUp size={12} />
            {compactNumber(mod.endorsements)}
          </span>
        </div>
      </div>
    </Panel>
  );
};

const Dashboard: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [manualSummaryReport, setManualSummaryReport] = React.useState("");
  const [manualSummaryStatus, setManualSummaryStatus] = React.useState("");
  const [showSchedulerDialog, setShowSchedulerDialog] = React.useState(false);
  const recommendedScrollRef = React.useRef<HTMLDivElement | null>(null);

  const { data: favorites = [] } = useQuery({
    queryKey: ["favorites", "refs"],
    queryFn: fetchFavoriteRefs,
  });

  const favoriteByModId = React.useMemo(() => mapFavoritesByModId(favorites), [favorites]);

  const favoriteMutation = useMutation({
    mutationFn: async (modId: number) => {
      const favorite = favoriteByModId.get(modId);
      if (favorite) {
        await removeFavorite(favorite.id);
        return;
      }
      await addFavorite({ mod_id: modId });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
      queryClient.invalidateQueries({ queryKey: ["stats"] });
    },
  });

  const handleToggleFavorite = (modId: number) => {
    favoriteMutation.mutate(modId);
  };

  const scrollRecommended = (direction: "left" | "right") => {
    const container = recommendedScrollRef.current;
    if (!container) return;
    const offset = Math.max(260, Math.floor(container.clientWidth * 0.75));
    container.scrollBy({
      left: direction === "left" ? -offset : offset,
      behavior: "smooth",
    });
  };

  const { data: stats, isLoading: statsLoading, isError: statsError, refetch: refetchStats } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });
  const {
    data: recommendationData,
    isLoading: recommendationsLoading,
    isError: recommendationsError,
    refetch: refetchRecommendations,
  } = useQuery({
    queryKey: ["dashboard-recommendations"],
    queryFn: () => fetchRecommendedMods(10),
  });
  const { data: recentJobsData, isError: recentJobsError } = useQuery({
    queryKey: ["dashboard-job-runs"],
    queryFn: () => fetchJobRuns(200, { metadata: "dashboard" }),
    refetchInterval: 15000,
  });
  const { data: schedulerStatus, isError: schedulerError } = useQuery({
    queryKey: ["dashboard-scheduler-status"],
    queryFn: fetchSchedulerStatus,
    refetchInterval: 30000,
  });
  const { data: settings, isError: settingsError } = useQuery({
    queryKey: ["settings"],
    queryFn: fetchSettings,
  });

  const recommendedMods = recommendationData?.items ?? [];
  const displayStats: Stats = stats ?? {
    total_mods: recommendationData?.total ?? 0,
    new_mods_this_week: 0,
    total_favorites: 0,
    total_rules: 0,
    unseen_updates: 0,
  };
  const showStatsLoading = statsLoading && recommendationData === undefined;
  const recentJobs = recentJobsData?.items ?? [];
  const latestSummaryJob = getLatestSummaryJob(recentJobs);
  const latestSummaryReportJob = getLatestSummaryReportJob(recentJobs);
  const latestSummaryReport = latestSummaryReportJob ? String(parseJobMetadata(latestSummaryReportJob.metadata_json).report || "") : "";
  const contentSummary = manualSummaryReport || latestSummaryReport;
  const latestSummaryJobMetadata = latestSummaryJob ? parseJobMetadata(latestSummaryJob.metadata_json) : {};
  const latestSummaryGenerated = latestSummaryJobMetadata.generated === true;
  const latestSummaryNoContent = latestSummaryJob && !latestSummaryGenerated;
  const contentSummarySource = manualSummaryReport
    ? t("dashboard.summarySourceManual")
    : latestSummaryNoContent
      ? t("dashboard.summarySourceScheduledNoContent", {
          time: formatTime(latestSummaryJob.finished_at || latestSummaryJob.started_at),
        })
      : latestSummaryReportJob
      ? t("dashboard.summarySourceScheduled", {
          time: formatTime(latestSummaryReportJob.finished_at || latestSummaryReportJob.started_at),
        })
      : t("dashboard.summarySourcePending");
  const activeProvider = settings?.llmProviders
    ?.filter((provider) => provider.enabled)
    .sort((a, b) => a.priority - b.priority)[0];

  const summaryReportMutation = useMutation({
    mutationFn: runSummaryReport,
    onMutate: () => {
      setManualSummaryStatus(t("dashboard.summaryGenerating"));
    },
    onSuccess: (result) => {
      if (result.generated && result.report) {
        setManualSummaryReport(result.report);
        setManualSummaryStatus(
          t("dashboard.summaryGeneratedMeta", {
            provider: result.provider || "unknown",
            model: result.model || "unknown",
            count: result.items_scanned ?? 0,
          }),
        );
        return;
      }
      if (result.reason === "missing_prompt") {
        setManualSummaryStatus(t("dashboard.summaryPromptMissing"));
        setManualSummaryReport("");
        return;
      }
      if (result.reason === "no_recent_mods") {
        setManualSummaryStatus(t("dashboard.summaryNoRecentMods"));
        setManualSummaryReport("");
        return;
      }
      setManualSummaryStatus(t("dashboard.summaryNoResult"));
      setManualSummaryReport("");
    },
    onError: (error) => {
      setManualSummaryStatus(
        t("dashboard.summaryGenerateFailed", {
          error: error instanceof Error ? error.message : "unknown",
        }),
      );
      setManualSummaryReport("");
    },
  });

  const schedulerMutation = useMutation({
    mutationFn: (nextRunning: boolean) => (nextRunning ? resumeScheduler() : pauseScheduler()),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["dashboard-scheduler-status"] });
    },
  });

  const refreshDashboard = () => {
    refetchStats();
    refetchRecommendations();
    queryClient.invalidateQueries({ queryKey: ["dashboard-job-runs"] });
    queryClient.invalidateQueries({ queryKey: ["dashboard-scheduler-status"] });
    queryClient.invalidateQueries({ queryKey: ["settings"] });
  };

  const visibleRecentJobs = recentJobs.slice(0, 5);
  const sortedSchedulerJobs = [...(schedulerStatus?.jobs ?? [])].sort((a, b) => {
    if (!a.next_run_time) return 1;
    if (!b.next_run_time) return -1;
    return new Date(a.next_run_time).getTime() - new Date(b.next_run_time).getTime();
  });
  const visibleSchedulerJobs = sortedSchedulerJobs.slice(0, 5);
  const systemItems = [
    {
      label: "Nexus Mods API",
      detail: statsError ? t("dashboard.statusUnavailable") : t("dashboard.statusReachable"),
      ok: !statsError,
    },
    {
      label: "Mod Database",
      detail: recommendationsError ? t("dashboard.statusUnavailable") : t("dashboard.statusReachable"),
      ok: !recommendationsError,
    },
    {
      label: activeProvider
        ? t("dashboard.llmServiceWithModel", { provider: activeProvider.provider, model: activeProvider.model || "-" })
        : t("dashboard.llmService"),
      detail: settingsError ? t("dashboard.statusUnavailable") : t("dashboard.statusConfigured"),
      ok: !settingsError && Boolean(activeProvider),
    },
    {
      label: t("dashboard.schedulerJobs"),
      detail: schedulerStatus?.running
        ? t("dashboard.nextJobsCount", { count: schedulerStatus.jobs.length })
        : t("dashboard.schedulerPaused"),
      ok: !schedulerError && Boolean(schedulerStatus?.running),
    },
  ];

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex h-screen">
        <AppSidebar active="dashboard" />

        <main className="flex-1 overflow-x-hidden overflow-y-auto">
          <div className="space-y-5 px-6 py-6 lg:px-8">
            <header className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-3xl font-bold tracking-normal text-slate-950">{t("dashboard.workbenchTitle")}</h1>
                  <Sparkles size={24} className="text-blue-600" />
                </div>
                <p className="mt-2 text-sm font-semibold text-slate-500">{t("dashboard.workbenchDesc")}</p>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span className="text-sm font-semibold text-slate-600">{formatDateTime(new Date())}</span>
                <FilterBarButton
                  type="button"
                  onClick={refreshDashboard}
                  className="text-slate-700"
                >
                  <RefreshCw size={17} />
                  <span className="ml-2">{t("dashboard.refreshData")}</span>
                </FilterBarButton>
                <FilterBarButton
                  type="button"
                  className="text-slate-700"
                  onClick={() => schedulerMutation.mutate(!(schedulerStatus?.running ?? false))}
                  disabled={schedulerMutation.isPending || schedulerError}
                >
                  {schedulerStatus?.running ? <Pause size={17} /> : <Play size={17} />}
                  <span className="ml-2">
                    {schedulerStatus?.running ? t("dashboard.pauseScheduler") : t("dashboard.resumeScheduler")}
                  </span>
                </FilterBarButton>
              </div>
            </header>

            {statsError ? (
              <div className="rounded-lg border border-rose-100 bg-white px-4 py-6 text-center shadow-sm">
                <p className="text-sm font-semibold text-slate-500">{t("dashboard.loadFailed")}</p>
                <Button variant="outline" size="sm" className="mt-3" onClick={() => refetchStats()}>
                  <RefreshCw size={14} className="mr-1.5" />
                  {t("dashboard.retry")}
                </Button>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
                {STAT_CARDS.map((card) => (
                  <StatCard
                    key={card.valueKey}
                    config={card}
                    value={displayStats[card.valueKey]}
                    loading={showStatsLoading}
                  />
                ))}
              </div>
            )}

            <div className="grid min-w-0 gap-5">
              <Panel as="section" padding="lg" className="min-w-0 max-w-full overflow-hidden">
                <div className="mb-4 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2">
                    <Sparkles size={22} className="text-blue-600" />
                    <h2 className="text-xl font-bold text-slate-950">{t("dashboard.intelSummary")}</h2>
                    <span className="text-xs font-semibold text-slate-400">{t("dashboard.lastAnalysis")}</span>
                  </div>
                  <Button
                    size="sm"
                    variant="ghost"
                    className="bg-slate-50 text-slate-700 hover:bg-slate-100"
                    onClick={() => summaryReportMutation.mutate()}
                    disabled={summaryReportMutation.isPending}
                  >
                    <RefreshCw size={14} className={summaryReportMutation.isPending ? "mr-1.5 animate-spin" : "mr-1.5"} />
                    {t("dashboard.rerunAnalysis")}
                  </Button>
                </div>

                <div className="min-w-0 rounded-lg border border-indigo-100 bg-indigo-50/60 p-4">
                  <div className="mb-2 flex items-center gap-2 text-indigo-700">
                    <MessageCircle size={20} />
                    <h3 className="font-bold">{t("dashboard.contentSummary")}</h3>
                    <span className="rounded-md border border-indigo-100 bg-white/80 px-2 py-0.5 text-xs font-semibold text-indigo-600">
                      {contentSummarySource}
                    </span>
                  </div>
                  <MarkdownText
                    className="text-sm font-medium text-slate-700"
                    text={contentSummary || t("dashboard.summaryReportNotGenerated", {
                      total: displayStats.total_mods,
                      weekly: displayStats.new_mods_this_week,
                    })}
                  />
                </div>

                {(manualSummaryStatus || manualSummaryReport) && (
                  <div className="mt-4 rounded-lg border border-indigo-100 bg-indigo-50 px-4 py-3">
                    {manualSummaryStatus && (
                      <p className="text-xs font-semibold text-indigo-800">{manualSummaryStatus}</p>
                    )}
                  </div>
                )}
              </Panel>

            </div>

            <div className="grid gap-5 xl:grid-cols-2">
              <Panel as="section" padding="lg" className="min-w-0 max-w-full overflow-hidden">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-xl font-bold text-slate-950">{t("dashboard.systemStatus")}</h2>
                  <span className="rounded-md bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700">
                    {systemItems.every((item) => item.ok) ? t("dashboard.allNormal") : t("dashboard.needsAttention")}
                  </span>
                </div>
                <div className="space-y-4">
                  {systemItems.map((item) => (
                    <div key={item.label} className="flex items-center gap-3">
                      <span className="flex h-9 w-9 items-center justify-center rounded-full bg-slate-50 text-slate-500">
                        {item.label === "Mod Database" ? <Database size={18} /> : <Clock size={18} />}
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-bold text-slate-800">{item.label}</p>
                        <p className="truncate text-xs font-semibold text-slate-400">{item.detail}</p>
                      </div>
                      <span className={`h-2.5 w-2.5 rounded-full ${item.ok ? "bg-emerald-500" : "bg-rose-500"}`} />
                    </div>
                  ))}
                </div>
                <div className="mt-5 rounded-lg border border-slate-100 bg-slate-50/80 p-3">
                  <div className="mb-3 flex items-center justify-between gap-2">
                    <p className="text-sm font-bold text-slate-800">{t("dashboard.schedulerPreview")}</p>
                    <div className="flex shrink-0 items-center gap-2">
                      <span className="rounded-md bg-white px-2 py-0.5 text-xs font-bold text-slate-500">
                        {t("common.total", { total: schedulerStatus?.jobs.length ?? 0 })}
                      </span>
                      {sortedSchedulerJobs.length > visibleSchedulerJobs.length && (
                        <button
                          type="button"
                          onClick={() => setShowSchedulerDialog(true)}
                          className="rounded-md bg-blue-50 px-2 py-0.5 text-xs font-bold text-blue-600 hover:bg-blue-100"
                        >
                          {t("dashboard.schedulerMore")}
                        </button>
                      )}
                    </div>
                  </div>
                  {schedulerError ? (
                    <p className="rounded-md bg-white px-3 py-3 text-sm font-semibold text-slate-500">
                      {t("dashboard.schedulerPreviewFailed")}
                    </p>
                  ) : visibleSchedulerJobs.length > 0 ? (
                    <div className="space-y-2">
                      {visibleSchedulerJobs.map((job) => (
                        <div key={job.id} className="flex items-center gap-3 rounded-md bg-white px-3 py-2">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600">
                            <Clock size={15} />
                          </span>
                          <div className="min-w-0 flex-1">
                            <p className="truncate text-sm font-bold text-slate-800" title={job.name}>
                              {job.name}
                            </p>
                            <p className="truncate text-xs font-semibold text-slate-400">
                              {job.id}
                            </p>
                          </div>
                          <span className="shrink-0 text-xs font-bold text-slate-500">
                            {formatTime(job.next_run_time)}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <p className="rounded-md bg-white px-3 py-3 text-sm font-semibold text-slate-500">
                      {t("dashboard.noScheduledJobs")}
                    </p>
                  )}
                </div>
              </Panel>

              <Panel as="section" padding="lg">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-xl font-bold text-slate-950">{t("dashboard.recentTasks")}</h2>
                  <Link to="/logs?tab=finished" className="text-sm font-bold text-blue-600 hover:text-blue-700">
                    {t("dashboard.viewAll")} →
                  </Link>
                </div>
                {recentJobsError ? (
                  <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm font-semibold text-slate-500">
                    {t("dashboard.tasksLoadFailed")}
                  </p>
                ) : visibleRecentJobs.length > 0 ? (
                  <div className="divide-y divide-slate-100">
                    {visibleRecentJobs.map((job) => (
                      <div key={job.id} className="flex items-center gap-3 py-3">
                        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-50 text-blue-600">
                          <Database size={16} />
                        </span>
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-bold text-slate-800">{getJobDisplayName(job)}</p>
                          <p className="truncate text-xs font-semibold text-slate-400">
                            {getJobDisplayName(job) === job.job_name ? "" : `${job.job_name} · `}
                            {t("dashboard.taskMeta", { scanned: job.items_scanned, matched: job.items_matched })}
                          </p>
                        </div>
                        <span className={`rounded-md px-2.5 py-1 text-xs font-bold ${jobStatusClass(job.status)}`}>
                          {job.status}
                        </span>
                        <span className="text-xs font-semibold text-slate-400">{formatTime(job.finished_at || job.started_at)}</span>
                      </div>
                    ))}
                  </div>
                ) : (
                  <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm font-semibold text-slate-500">
                    {t("dashboard.noRecentTasks")}
                  </p>
                )}
              </Panel>
            </div>

            <div className="grid min-w-0 grid-cols-1 gap-5">
              <Panel as="section" padding="lg">
                <div className="mb-4 flex items-center justify-between">
                  <h2 className="text-xl font-bold text-slate-950">{t("dashboard.recommendedMods")}</h2>
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={() => scrollRecommended("left")}
                      className="hidden h-8 w-8 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 lg:inline-flex"
                      aria-label="Scroll Left"
                    >
                      <ChevronLeft size={16} />
                    </button>
                    <button
                      type="button"
                      onClick={() => scrollRecommended("right")}
                      className="hidden h-8 w-8 items-center justify-center rounded-md border border-slate-200 bg-white text-slate-600 hover:bg-slate-50 lg:inline-flex"
                      aria-label="Scroll Right"
                    >
                      <ChevronRight size={16} />
                    </button>
                    <Link to="/discover" className="text-sm font-bold text-blue-600 hover:text-blue-700">
                      {t("dashboard.viewAll")} →
                    </Link>
                  </div>
                </div>
                {recommendationsLoading ? (
                  <div className="no-scrollbar flex w-full min-w-0 max-w-full gap-4 overflow-x-auto pb-2">
                    {[0, 1, 2, 3, 4].map((item) => (
                      <div key={item} className="h-64 w-[220px] shrink-0 animate-pulse rounded-lg bg-slate-100" />
                    ))}
                  </div>
                ) : recommendedMods.length > 0 ? (
                  <div className="min-w-0 max-w-full overflow-hidden">
                    <div
                      ref={recommendedScrollRef}
                      className="no-scrollbar flex w-full min-w-0 max-w-full gap-4 overflow-x-auto pb-2"
                      onWheel={(e) => {
                        if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
                          e.preventDefault();
                          e.currentTarget.scrollLeft += e.deltaY;
                        }
                      }}
                    >
                      {recommendedMods.map((mod) => (
                        <RecommendedModCard
                          key={mod.id}
                          mod={mod}
                          isFavorited={favoriteByModId.has(mod.id)}
                          onToggleFavorite={handleToggleFavorite}
                        />
                      ))}
                    </div>
                  </div>
                ) : (
                  <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-4 py-10 text-center">
                    <p className="text-sm font-semibold text-slate-500">{t("dashboard.noRecommendations")}</p>
                  </div>
                )}
              </Panel>
            </div>

            <section className="flex flex-col gap-4 rounded-lg border border-blue-200 bg-blue-50/60 p-5 shadow-sm md:flex-row md:items-center md:justify-between">
              <div className="flex items-center gap-4">
                <span className="flex h-14 w-14 items-center justify-center rounded-xl border border-blue-100 bg-white text-blue-600 shadow-sm">
                  <Bot size={28} />
                </span>
                <div>
                  <h2 className="text-xl font-bold text-blue-700">{t("dashboard.agentTitle")}</h2>
                  <p className="mt-1 text-sm font-semibold text-slate-500">{t("dashboard.agentDesc")}</p>
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3">
                <span className="rounded-lg border border-blue-100 bg-white px-4 py-2 text-sm font-semibold text-slate-600">
                  {t("dashboard.agentPrompt1")}
                </span>
                <span className="rounded-lg border border-blue-100 bg-white px-4 py-2 text-sm font-semibold text-slate-600">
                  {t("dashboard.agentPrompt2")}
                </span>
                <Link to="/agent">
                  <Button className="h-11 rounded-lg px-5">
                    <MessageCircle size={17} />
                    <span className="ml-2">{t("dashboard.startChat")}</span>
                  </Button>
                </Link>
              </div>
            </section>
          </div>
        </main>
      </div>
      {showSchedulerDialog && (
        <ModalShell
          open={showSchedulerDialog}
          onClose={() => setShowSchedulerDialog(false)}
          size="md"
          panelClassName="max-h-[82vh] overflow-hidden"
        >
          <ModalHeader
            title={
              <span className="text-lg font-bold text-slate-950">
                {t("dashboard.schedulerPreview")}
              </span>
            }
            subtitle={<span className="font-semibold">{t("common.total", { total: sortedSchedulerJobs.length })}</span>}
            onClose={() => setShowSchedulerDialog(false)}
            closeAriaLabel={t("common.close")}
            className="border-b border-slate-100 px-5 py-4"
          />
            <div className="max-h-[64vh] overflow-y-auto p-4">
              {sortedSchedulerJobs.length > 0 ? (
                <div className="space-y-2">
                  {sortedSchedulerJobs.map((job) => (
                    <div key={job.id} className="flex items-center gap-3 rounded-lg border border-slate-100 px-3 py-3">
                      <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-blue-50 text-blue-600">
                        <Clock size={16} />
                      </span>
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-bold text-slate-900" title={job.name}>
                          {job.name}
                        </p>
                        <p className="truncate text-xs font-semibold text-slate-400">{job.id}</p>
                      </div>
                      <span className="shrink-0 rounded-md bg-slate-50 px-2.5 py-1 text-xs font-bold text-slate-600">
                        {formatTime(job.next_run_time)}
                      </span>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="rounded-lg bg-slate-50 px-3 py-6 text-center text-sm font-semibold text-slate-500">
                  {t("dashboard.noScheduledJobs")}
                </p>
              )}
            </div>
        </ModalShell>
      )}
    </div>
  );
};

export default Dashboard;
