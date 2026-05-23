import React, { useState, useMemo, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  Play,
  Loader2,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  LayoutGrid,
  List,
  ExternalLink,
  Heart,
  EyeOff,
  Clock,
  Undo2,
  X,
  Gamepad2,
  Database,
  ShieldCheck,
  Languages,
  Info,
  TrendingUp,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import AppSidebar from "@/components/layout/AppSidebar";
import { ModCard } from "@/components/ModCard";
import { ModStatsLine } from "@/components/ModStatsLine";
import { SourceBadge } from "@/components/SourceBadge";
import {
  fetchIgnoredMods,
  fetchModGames,
  fetchMods,
  generateModIntroduction,
  ignoreMod,
  regenerateModSummary,
  unignoreMod,
} from "@/api/mods";
import { fetchJobRun, runDiscoveryAll } from "@/api/jobs";
import { addFavorite, fetchFavorites, removeFavorite } from "@/api/favorites";
import { useUIStore } from "@/stores/uiStore";
import { formatModSummary } from "@/utils/modSummary";
import type { Favorite, ModItem, ModSource, AdultPolicy, SummaryMode } from "@/types";

const PAGE_SIZE = 24;
type DiscoverViewMode = "card" | "list";

function SkeletonCard() {
  return (
    <div className="rounded-lg border border-slate-200 bg-white shadow-sm overflow-hidden animate-pulse">
      <div className="aspect-[300/169] bg-gray-200" />
      <div className="p-4 space-y-2">
        <div className="h-4 bg-gray-200 rounded w-3/4" />
        <div className="flex gap-3">
          <div className="h-3 bg-gray-200 rounded w-16" />
          <div className="h-3 bg-gray-200 rounded w-16" />
          <div className="h-3 bg-gray-200 rounded w-20" />
        </div>
        <div className="h-3 bg-gray-200 rounded w-full" />
        <div className="h-3 bg-gray-200 rounded w-2/3" />
        <div className="h-9 bg-gray-200 rounded mt-2" />
      </div>
    </div>
  );
}

function ToolbarSelect({
  label,
  value,
  onChange,
  icon,
  children,
  className = "",
}: {
  label: string;
  value: string;
  onChange: (event: React.ChangeEvent<HTMLSelectElement>) => void;
  icon: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <label className={`block min-w-0 ${className}`}>
      <span className="mb-1.5 block text-xs font-semibold text-slate-500">{label}</span>
      <span className="relative block">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500">
          {icon}
        </span>
        <select
          value={value}
          onChange={onChange}
          className="h-11 w-full appearance-none rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-9 text-sm font-semibold text-slate-700 shadow-sm outline-none transition focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
        >
          {children}
        </select>
        <ChevronRight
          size={15}
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rotate-90 text-slate-400"
        />
      </span>
    </label>
  );
}

const Discover: React.FC = () => {
  const { t } = useTranslation();

  const SORTS = [
    { value: "updated_at_remote", label: t("discover.sortNewest") },
    { value: "first_seen_at", label: t("discover.sortFirstSeen") },
    { value: "downloads", label: t("discover.sortDownloads") },
    { value: "endorsements", label: t("discover.sortEndorsements") },
  ];

  const ADULT_OPTIONS: { value: AdultPolicy; label: string }[] = [
    { value: "exclude", label: t("discover.adultExclude") },
    { value: "include", label: t("discover.adultInclude") },
    { value: "only", label: t("discover.adultOnly") },
  ];

  const queryClient = useQueryClient();
  const { summaryMode, setSummaryMode } = useUIStore();
  const [game, setGame] = useState("");
  const [searchText, setSearchText] = useState("");
  const [search, setSearch] = useState("");
  const [source, setSource] = useState<ModSource | "">("");
  const [sort, setSort] = useState("updated_at_remote");
  const [adultPolicy, setAdultPolicy] = useState<AdultPolicy>("include");
  const [viewMode, setViewMode] = useState<DiscoverViewMode>("card");
  const [page, setPage] = useState(1);
  const [isRunning, setIsRunning] = useState(false);
  const [lastResult, setLastResult] = useState("");
  const [ignoredListOpen, setIgnoredListOpen] = useState(false);
  const [regeneratingSummaryIds, setRegeneratingSummaryIds] = useState<Set<number>>(new Set());
  const [metricsNoticeVisible, setMetricsNoticeVisible] = useState(true);
  const discoveryRunRef = useRef(0);

  const offset = (page - 1) * PAGE_SIZE;

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const next = searchText.trim();
      setSearch((current) => {
        if (current === next) return current;
        setPage(1);
        return next;
      });
    }, 300);
    return () => window.clearTimeout(timer);
  }, [searchText]);

  const { data: gameOptions = [] } = useQuery({
    queryKey: ["mod-games"],
    queryFn: fetchModGames,
  });
  const { data: favorites = [] } = useQuery({
    queryKey: ["favorites"],
    queryFn: fetchFavorites,
  });

  const favoriteByModId = useMemo(() => {
    const pairs = new Map<number, Favorite>();
    for (const favorite of favorites) {
      const modId = getFavoriteModId(favorite);
      if (modId !== undefined) {
        pairs.set(modId, favorite);
      }
    }
    return pairs;
  }, [favorites]);

  const queryParams = useMemo(
    () => ({
      game: game || undefined,
      search: search || undefined,
      source: source || undefined,
      adultContent: adultPolicy,
      sortBy: sort,
      sortOrder: "desc" as const,
      offset,
      limit: PAGE_SIZE,
    }),
    [adultPolicy, game, offset, search, sort, source]
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["mods", queryParams],
    queryFn: () => fetchMods(queryParams),
    refetchInterval: summaryMode === "original" ? false : 15000,
  });
  const { data: ignoredMods, isLoading: ignoredLoading } = useQuery({
    queryKey: ["mods", "ignored"],
    queryFn: () =>
      fetchIgnoredMods({
        sortBy: "first_seen_at",
        sortOrder: "desc",
        offset: 0,
        limit: 100,
      }),
    enabled: ignoredListOpen,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;
  const updatedLabel = isLoading ? t("common.loading") : t("discover.listLoaded");

  const handleGameChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setGame(e.target.value);
    setPage(1);
  };

  const handleSourceChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSource(e.target.value as ModSource | "");
    setPage(1);
  };

  const handleSortChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setSort(e.target.value);
    setPage(1);
  };

  const handleAdultChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    setAdultPolicy(e.target.value as AdultPolicy);
    setPage(1);
  };

  const handleRunDiscovery = async () => {
    const runToken = discoveryRunRef.current + 1;
    discoveryRunRef.current = runToken;
    setIsRunning(true);
    setLastResult("");
    const isCurrentRun = () => discoveryRunRef.current === runToken;
    try {
      const result = await runDiscoveryAll();
      if (!isCurrentRun()) return;
      setLastResult(t("jobs.queued", { jobId: result.job_id }));
      for (let i = 0; i < 60; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        if (!isCurrentRun()) return;
        const job = await fetchJobRun(result.job_id);
        if (!isCurrentRun()) return;
        if (job.status === "queued" || job.status === "running") {
          setLastResult(t("jobs.running", { jobId: result.job_id, status: t(`jobs.status.${job.status}`) }));
          continue;
        }
        if (job.status === "failed") {
          setLastResult(t("jobs.failed", { error: job.error_message || t("jobs.failedDefault") }));
          return;
        }
        setLastResult(t("jobs.foundMods", { count: job.items_matched }));
        refetch();
        return;
      }
    } catch (e) {
      if (isCurrentRun()) {
        setLastResult(t("jobs.failed", { error: (e as Error).message }));
      }
    } finally {
      if (isCurrentRun()) {
        setIsRunning(false);
      }
    }
  };

  useEffect(() => {
    return () => {
      discoveryRunRef.current += 1;
    };
  }, []);

  const ignoreMutation = useMutation({
    mutationFn: ignoreMod,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mods"] });
      queryClient.invalidateQueries({ queryKey: ["mods", "ignored"] });
    },
  });

  const handleIgnore = (modId: number) => {
    ignoreMutation.mutate(modId);
  };

  const unignoreMutation = useMutation({
    mutationFn: unignoreMod,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mods"] });
      queryClient.invalidateQueries({ queryKey: ["mods", "ignored"] });
      queryClient.invalidateQueries({ queryKey: ["mod-games"] });
    },
  });

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
    },
  });

  const handleToggleFavorite = (modId: number) => {
    favoriteMutation.mutate(modId);
  };

  const regenerateSummaryMutation = useMutation({
    mutationFn: regenerateModSummary,
    onMutate: async (modId: number) => {
      setRegeneratingSummaryIds((prev) => {
        const next = new Set(prev);
        next.add(modId);
        return next;
      });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mods"] });
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["mods"] }), 5000);
    },
    onSettled: (_data, _error, modId) => {
      setRegeneratingSummaryIds((prev) => {
        const next = new Set(prev);
        if (typeof modId === "number") {
          next.delete(modId);
        }
        return next;
      });
    },
  });

  const handleRegenerateSummary = (modId: number) => {
    regenerateSummaryMutation.mutate(modId);
  };

  const generateIntroductionMutation = useMutation({
    mutationFn: generateModIntroduction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mods"] });
    },
  });

  const handleGenerateIntroduction = async (modId: number) => {
    const result = await generateIntroductionMutation.mutateAsync(modId);
    return result.content;
  };

  const renderPagination = () => {
    if (totalPages <= 1) return null;

    const pages: number[] = [];
    const maxVisible = 5;
    let start = Math.max(1, page - Math.floor(maxVisible / 2));
    let end = Math.min(totalPages, start + maxVisible - 1);
    if (end - start + 1 < maxVisible) {
      start = Math.max(1, end - maxVisible + 1);
    }
    for (let i = start; i <= end; i++) {
      pages.push(i);
    }

    return (
      <div className="flex items-center justify-center gap-1 mt-8">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => setPage((p) => p - 1)}
        >
          <ChevronLeft size={16} />
        </Button>

        {start > 1 && (
          <>
            <Button variant="ghost" size="sm" onClick={() => setPage(1)}>
              1
            </Button>
            {start > 2 && <span className="text-gray-400 px-1">...</span>}
          </>
        )}

        {pages.map((p) => (
          <Button
            key={p}
            variant={p === page ? "default" : "ghost"}
            size="sm"
            onClick={() => setPage(p)}
          >
            {p}
          </Button>
        ))}

        {end < totalPages && (
          <>
            {end < totalPages - 1 && <span className="text-gray-400 px-1">...</span>}
            <Button variant="ghost" size="sm" onClick={() => setPage(totalPages)}>
              {totalPages}
            </Button>
          </>
        )}

        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => setPage((p) => p + 1)}
        >
          <ChevronRight size={16} />
        </Button>
      </div>
    );
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex h-screen">
        <AppSidebar active="discover" />

        <main className="flex-1 overflow-y-auto">
          <div className="px-6 py-6 lg:px-8">
            <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h1 className="text-3xl font-bold tracking-normal text-slate-950">{t("discover.title")}</h1>
                <p className="mt-2 text-sm font-medium text-slate-500">{t("discover.subtitle")}</p>
              </div>
              <Button
                onClick={handleRunDiscovery}
                disabled={isRunning}
                className="h-12 rounded-lg bg-blue-600 px-5 text-base shadow-sm shadow-blue-200 hover:bg-blue-700"
              >
                {isRunning ? (
                  <Loader2 size={18} className="animate-spin" />
                ) : (
                  <Play size={18} />
                )}
                <span className="ml-2">
                  {isRunning ? t("discover.running") : t("discover.runDiscovery")}
                </span>
              </Button>
            </div>

            <section className="mb-6 rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
              <label className="mb-4 block">
                <span className="mb-1.5 block text-xs font-semibold text-slate-500">{t("discover.search")}</span>
                <span className="relative block">
                  <Search
                    size={18}
                    className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500"
                  />
                  <input
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    placeholder={t("discover.searchPlaceholder")}
                    className="h-11 w-full rounded-lg border border-slate-200 bg-white py-2 pl-10 pr-10 text-sm font-semibold text-slate-700 shadow-sm outline-none transition placeholder:text-slate-400 focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
                  />
                  {searchText && (
                    <button
                      type="button"
                      onClick={() => {
                        setSearchText("");
                        setSearch("");
                        setPage(1);
                      }}
                      className="absolute right-3 top-1/2 -translate-y-1/2 rounded-md p-0.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
                      aria-label={t("common.close")}
                    >
                      <X size={16} />
                    </button>
                  )}
                </span>
              </label>

              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-[1.05fr_1.05fr_1fr_1fr_0.75fr]">
                <ToolbarSelect
                  label={t("discover.game")}
                  value={game}
                  onChange={handleGameChange}
                  icon={<Gamepad2 size={18} />}
                >
                      <option value="">{t("discover.allGames")}</option>
                      {gameOptions.map((g) => (
                        <option key={g.value} value={g.value}>
                          {g.label} ({g.count})
                        </option>
                      ))}
                </ToolbarSelect>

                <ToolbarSelect
                  label={t("discover.source")}
                  value={source}
                  onChange={handleSourceChange}
                  icon={<Database size={18} />}
                >
                      <option value="">{t("discover.allSources")}</option>
                      <option value="nexusmods">{t("discover.sourceNexusmods")}</option>
                      <option value="loverslab">{t("discover.sourceLoverslab")}</option>
                </ToolbarSelect>

                <ToolbarSelect
                  label={t("discover.sortBy")}
                  value={sort}
                  onChange={handleSortChange}
                  icon={<Clock size={18} />}
                >
                      {SORTS.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                </ToolbarSelect>

                <ToolbarSelect
                  label={t("discover.adultPolicy")}
                  value={adultPolicy}
                  onChange={handleAdultChange}
                  icon={<ShieldCheck size={18} />}
                >
                      {ADULT_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                </ToolbarSelect>

                <ToolbarSelect
                  label={t("settings.summaryMode")}
                  value={summaryMode}
                  onChange={(e) => setSummaryMode(e.target.value as SummaryMode)}
                  icon={<Languages size={18} />}
                >
                      <option value="original">{t("summary.original")}</option>
                      <option value="translated">{t("summary.translated")}</option>
                      <option value="bilingual">{t("summary.bilingual")}</option>
                </ToolbarSelect>
              </div>

              {metricsNoticeVisible && (
                <div className="mt-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm font-semibold leading-6 text-amber-800">
                  <Info size={18} className="mt-0.5 shrink-0" />
                  <span className="min-w-0 flex-1">{t("discover.loverslabMetricsNotice")}</span>
                  <button
                    type="button"
                    className="shrink-0 rounded-md p-0.5 text-amber-700 hover:bg-amber-100"
                    onClick={() => setMetricsNoticeVisible(false)}
                    aria-label={t("common.close")}
                  >
                    <X size={16} />
                  </button>
                </div>
              )}
            </section>

            {lastResult && (
              <p className="mb-4 rounded-lg border border-blue-100 bg-blue-50 px-4 py-2 text-sm font-medium text-blue-700">
                {lastResult}
              </p>
            )}

            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
                <span className="inline-flex items-center gap-2 font-bold text-blue-600">
                  <TrendingUp size={18} />
                  {t("discover.resultsCount", { count: data?.total ?? 0 })}
                </span>
                <span className="hidden h-5 w-px bg-slate-200 sm:block" />
                <span className="font-medium">{updatedLabel}</span>
                <button
                  type="button"
                  onClick={() => refetch()}
                  className="inline-flex items-center rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-blue-600"
                  title={t("discover.retry")}
                >
                  <RefreshCw size={17} />
                </button>
              </div>

              <div className="flex items-center gap-3">
                <div className="inline-flex rounded-lg border border-slate-200 bg-white p-1 shadow-sm">
                  <button
                    type="button"
                    className={`inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold transition ${
                      viewMode === "card"
                        ? "bg-blue-600 text-white shadow-sm"
                        : "text-slate-600 hover:bg-slate-50"
                    }`}
                    onClick={() => setViewMode("card")}
                  >
                    <LayoutGrid size={17} />
                    {t("discover.viewCard")}
                  </button>
                  <button
                    type="button"
                    className={`inline-flex h-10 items-center gap-2 rounded-md px-3 text-sm font-semibold transition ${
                      viewMode === "list"
                        ? "bg-blue-600 text-white shadow-sm"
                        : "text-slate-600 hover:bg-slate-50"
                    }`}
                    onClick={() => setViewMode("list")}
                  >
                    <List size={17} />
                    {t("discover.viewList")}
                  </button>
                </div>
                <Button
                  type="button"
                  variant="outline"
                  className="h-11 rounded-lg border-slate-200 bg-white px-4 text-slate-700 shadow-sm"
                  onClick={() => setIgnoredListOpen(true)}
                >
                  <EyeOff size={17} />
                  <span className="ml-2">{t("discover.hiddenList")}</span>
                </Button>
              </div>
            </div>

            {isLoading ? (
              <div className={viewMode === "card" ? "grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3" : "space-y-3"}>
                {Array.from({ length: 6 }).map((_, i) => (
                  <SkeletonCard key={i} />
                ))}
              </div>
            ) : isError ? (
              <div className="text-center py-16">
                <p className="text-red-500 mb-4">
                  {(error as Error)?.message || t("discover.loadFailed")}
                </p>
                <Button onClick={() => refetch()}>
                  <RefreshCw size={16} />
                  <span className="ml-1.5">{t("discover.retry")}</span>
                </Button>
              </div>
            ) : data && data.items.length === 0 ? (
              <div className="text-center py-16">
                <div className="text-gray-400 mb-2">
                  <Search size={48} className="mx-auto" />
                </div>
                <p className="text-gray-500 text-sm">{t("discover.noMods")}</p>
                <p className="text-gray-400 text-xs mt-1">
                  {t("discover.configureHint")}
                </p>
              </div>
            ) : (
              <>
                {viewMode === "card" ? (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
                    {data?.items.map((mod) => (
                      <ModCard
                        key={mod.id}
                        mod={mod}
                        isFavorited={favoriteByModId.has(mod.id)}
                        onToggleFavorite={() => handleToggleFavorite(mod.id)}
                        onIgnore={() => handleIgnore(mod.id)}
                        onRegenerateSummary={() => handleRegenerateSummary(mod.id)}
                        regeneratingSummary={regeneratingSummaryIds.has(mod.id)}
                        onGenerateIntroduction={() => handleGenerateIntroduction(mod.id)}
                        generatingIntroduction={generateIntroductionMutation.isPending && generateIntroductionMutation.variables === mod.id}
                      />
                    ))}
                  </div>
                ) : (
                  <div className="space-y-3">
                    {data?.items.map((mod) => {
                      const gameLabel = mod.game || mod.game_domain || "";
                      const summary = formatModSummary({
                        original: mod.original_summary,
                        translated: mod.translated_summary,
                        mode: summaryMode,
                      });
                      return (
                        <Card key={mod.id}>
                          <CardContent className="py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0 flex-1 space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <SourceBadge source={mod.source} />
                                  {mod.adult_content === true && (
                                    <span className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700">
                                      NSFW
                                    </span>
                                  )}
                                  {gameLabel && (
                                    <span className="inline-flex items-center rounded-md border border-gray-300 bg-white px-2 py-0.5 text-xs text-gray-600">
                                      {gameLabel}
                                    </span>
                                  )}
                                </div>

                                <a
                                  href={mod.url}
                                  target="_blank"
                                  rel="noopener noreferrer"
                                  className="block truncate text-base font-semibold text-gray-900 hover:text-blue-600"
                                  title={mod.title}
                                >
                                  {mod.title}
                                </a>

                                <ModStatsLine
                                  downloads={mod.downloads}
                                  endorsements={mod.endorsements}
                                  updatedAt={mod.updated_at_remote}
                                  className="text-gray-500"
                                />

                                {summary && (
                                  <p className="line-clamp-2 whitespace-pre-line text-sm text-gray-600">
                                    {summary}
                                  </p>
                                )}
                              </div>

                              <div className="flex shrink-0 items-center gap-1">
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleToggleFavorite(mod.id)}
                                  title={favoriteByModId.has(mod.id) ? t("mod.unfavorite") : t("mod.favorite")}
                                >
                                  <Heart size={14} className={favoriteByModId.has(mod.id) ? "fill-red-500 text-red-500" : ""} />
                                </Button>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  onClick={() => handleIgnore(mod.id)}
                                  title={t("mod.ignore")}
                                >
                                  <EyeOff size={14} />
                                </Button>
                                <a href={mod.url} target="_blank" rel="noopener noreferrer">
                                  <Button type="button" variant="outline" size="sm">
                                    <ExternalLink size={14} />
                                  </Button>
                                </a>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>
                )}
                {renderPagination()}
              </>
            )}
          </div>
        </main>
      </div>
      {ignoredListOpen && (
        <IgnoredModsDialog
          items={ignoredMods?.items || []}
          total={ignoredMods?.total || 0}
          loading={ignoredLoading}
          restoringId={unignoreMutation.variables}
          onClose={() => setIgnoredListOpen(false)}
          onRestore={(modId) => unignoreMutation.mutate(modId)}
        />
      )}
    </div>
  );
};

function IgnoredModsDialog({
  items,
  total,
  loading,
  restoringId,
  onClose,
  onRestore,
}: {
  items: ModItem[];
  total: number;
  loading: boolean;
  restoringId?: number;
  onClose: () => void;
  onRestore: (modId: number) => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
      <div className="flex max-h-[82vh] w-full max-w-3xl flex-col overflow-hidden rounded-lg bg-white shadow-xl">
        <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
          <div>
            <h3 className="text-base font-semibold text-gray-900">{t("discover.hiddenList")}</h3>
            <p className="mt-0.5 text-xs text-gray-500">
              {t("discover.hiddenListHint", { total })}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
          >
            <X size={18} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-gray-500">
              <Loader2 size={16} className="animate-spin" />
              {t("common.loading")}
            </div>
          ) : items.length === 0 ? (
            <div className="py-12 text-center text-sm text-gray-500">
              {t("discover.hiddenEmpty")}
            </div>
          ) : (
            <div className="divide-y divide-gray-100">
              {items.map((item) => (
                <div key={item.id} className="flex items-start gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <SourceBadge source={item.source} />
                      <span className="text-xs text-gray-500">{item.game || item.game_domain || "-"}</span>
                    </div>
                    <a
                      href={item.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="mt-1 block truncate text-sm font-semibold text-gray-900 hover:text-blue-600"
                      title={item.title}
                    >
                      {item.title}
                    </a>
                    {item.original_summary && (
                      <p className="mt-1 line-clamp-2 text-xs leading-5 text-gray-500">
                        {item.original_summary}
                      </p>
                    )}
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => onRestore(item.id)}
                    disabled={restoringId === item.id}
                  >
                    {restoringId === item.id ? (
                      <Loader2 size={14} className="animate-spin" />
                    ) : (
                      <Undo2 size={14} />
                    )}
                    <span className="ml-1">{t("discover.restoreHidden")}</span>
                  </Button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function getFavoriteModId(favorite: Favorite): number | undefined {
  const raw = favorite as Favorite & { mod_id?: number };
  return raw.mod_id ?? favorite.modId;
}

export default Discover;
