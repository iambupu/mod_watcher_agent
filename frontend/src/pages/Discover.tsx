import React, { useState, useMemo, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
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
  Gamepad2,
  Database,
  ShieldCheck,
  Languages,
  TrendingUp,
  DownloadCloud,
  Search,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ModalHeader, ModalShell } from "@/components/ui/Modal";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { FilterBarButton, FilterButtonGroup, FilterInput, FilterSelect } from "@/components/ui/FilterControls";
import AppSidebar from "@/components/layout/AppSidebar";
import { ModCard } from "@/components/ModCard";
import { ModStatsLine } from "@/components/ModStatsLine";
import { SourceBadge } from "@/components/SourceBadge";
import { ModFilterPanel } from "@/components/ModFilterPanel";
import { Panel } from "@/components/ui/Panel";
import {
  fetchIgnoredMods,
  fetchModGames,
  fetchMods,
  generateModIntroduction,
  ignoreMod,
  unignoreMod,
} from "@/api/mods";
import { importNexusModsGame, pollJobRun, runDiscoveryAll } from "@/api/jobs";
import { addFavorite, favoriteByModId as mapFavoritesByModId, fetchFavorites, removeFavorite } from "@/api/favorites";
import { useSummaryRegeneration } from "@/hooks/useSummaryRegeneration";
import { useUIStore } from "@/stores/uiStore";
import { formatModSummary } from "@/utils/modSummary";
import { formatModTitle } from "@/utils/modTitle";
import { isAdultContent } from "@/utils/modAdult";
import { parseIntegerInput, parseWholeIntegerInput } from "@/utils/numberInput";
import type { ModItem, ModSource, AdultPolicy, SummaryMode } from "@/types";

const PAGE_SIZE_OPTIONS = [20, 50, 80, 180] as const;
type PageSize = (typeof PAGE_SIZE_OPTIONS)[number];
const DEFAULT_PAGE_SIZE: PageSize = 20;
const DISCOVER_PAGE_SIZE_STORAGE_KEY = "modWatcher.discover.pageSize";
type DiscoverViewMode = "card" | "list";

function isPageSize(value: number): value is PageSize {
  return PAGE_SIZE_OPTIONS.includes(value as PageSize);
}

function getInitialPageSize(): PageSize {
  if (typeof window === "undefined") return DEFAULT_PAGE_SIZE;
  try {
    const stored = parseWholeIntegerInput(window.localStorage.getItem(DISCOVER_PAGE_SIZE_STORAGE_KEY) || "");
    return typeof stored === "number" && isPageSize(stored) ? stored : DEFAULT_PAGE_SIZE;
  } catch {
    return DEFAULT_PAGE_SIZE;
  }
}

function savePageSize(pageSize: PageSize) {
  try {
    window.localStorage.setItem(DISCOVER_PAGE_SIZE_STORAGE_KEY, String(pageSize));
  } catch {
    // Ignore storage failures so the selector remains usable in restricted browsers.
  }
}

function SkeletonCard() {
  return (
    <Panel padding="none" className="overflow-hidden animate-pulse">
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
    </Panel>
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
  const [contentLanguage, setContentLanguage] = useState("any");
  const [sort, setSort] = useState("updated_at_remote");
  const [adultPolicy, setAdultPolicy] = useState<AdultPolicy>("include");
  const [viewMode, setViewMode] = useState<DiscoverViewMode>("card");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<PageSize>(getInitialPageSize);
  const [isRunning, setIsRunning] = useState(false);
  const [isImportingGame, setIsImportingGame] = useState(false);
  const [importDialogOpen, setImportDialogOpen] = useState(false);
  const [importGameDomain, setImportGameDomain] = useState("");
  const [pageInput, setPageInput] = useState("1");
  const [lastResult, setLastResult] = useState("");
  const [ignoredListOpen, setIgnoredListOpen] = useState(false);
  const [pendingHideModId, setPendingHideModId] = useState<number | null>(null);
  const [pendingUnfavoriteModId, setPendingUnfavoriteModId] = useState<number | null>(null);
  const discoveryRunRef = useRef(0);
  const gameImportRunRef = useRef(0);

  const offset = (page - 1) * pageSize;

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

  const favoriteByModId = useMemo(() => mapFavoritesByModId(favorites), [favorites]);

  const queryParams = useMemo(
    () => ({
      game: game || undefined,
      search: search || undefined,
      source: source || undefined,
      contentLanguage: contentLanguage === "any" ? undefined : contentLanguage,
      adultContent: adultPolicy,
      sortBy: sort,
      sortOrder: "desc" as const,
      offset,
      limit: pageSize,
    }),
    [adultPolicy, contentLanguage, game, offset, pageSize, search, sort, source]
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

  const totalPages = data ? Math.ceil(data.total / pageSize) : 0;
  const updatedLabel = isLoading ? t("common.loading") : t("discover.listLoaded");

  useEffect(() => {
    if (!data || totalPages <= 0) return;
    if (page > totalPages) {
      setPage(totalPages);
    }
  }, [data, page, totalPages]);

  useEffect(() => {
    setPageInput(String(page));
  }, [page]);

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
      const pollResult = await pollJobRun(result.job_id, {
        isActive: isCurrentRun,
        onRunning: (job) => {
          setLastResult(t("jobs.running", { jobId: result.job_id, status: t(`jobs.status.${job.status}`) }));
        },
      });
      if (pollResult.status === "cancelled") return;
      if (pollResult.status === "timeout") {
        setLastResult(t("jobs.timeout"));
        return;
      }
      const job = pollResult.job;
      if (job.status === "failed") {
        setLastResult(t("jobs.failed", { error: job.error_message || t("jobs.failedDefault") }));
        return;
      }
      setLastResult(t("jobs.foundMods", { count: job.items_matched }));
      refetch();
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

  const handleImportNexusGame = async () => {
    const gameDomainName = importGameDomain.trim().toLowerCase();
    if (!gameDomainName) {
      setLastResult(t("discover.importGameRequired"));
      return;
    }
    const runToken = gameImportRunRef.current + 1;
    gameImportRunRef.current = runToken;
    setIsImportingGame(true);
    setLastResult("");
    const isCurrentRun = () => gameImportRunRef.current === runToken;
    try {
      const result = await importNexusModsGame({ gameDomainName });
      if (!isCurrentRun()) return;
      setLastResult(t("discover.importQueued", { jobId: result.job_id, game: gameDomainName }));
      setImportDialogOpen(false);
      setImportGameDomain("");
      const pollResult = await pollJobRun(result.job_id, {
        attempts: 120,
        isActive: isCurrentRun,
        onRunning: (job) => {
          setLastResult(t("jobs.running", { jobId: result.job_id, status: t(`jobs.status.${job.status}`) }));
        },
      });
      if (pollResult.status === "cancelled") return;
      if (pollResult.status === "timeout") {
        setLastResult(t("jobs.timeout"));
        return;
      }
      const job = pollResult.job;
      if (job.status === "failed") {
        setLastResult(t("jobs.failed", { error: job.error_message || t("jobs.failedDefault") }));
        return;
      }
      setLastResult(t("discover.importFinished", { created: job.items_matched, scanned: job.items_scanned }));
      queryClient.invalidateQueries({ queryKey: ["mod-games"] });
      refetch();
    } catch (e) {
      if (isCurrentRun()) {
        setLastResult(t("jobs.failed", { error: (e as Error).message }));
      }
    } finally {
      if (isCurrentRun()) {
        setIsImportingGame(false);
      }
    }
  };

  useEffect(() => {
    return () => {
      discoveryRunRef.current += 1;
      gameImportRunRef.current += 1;
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
    setPendingHideModId(modId);
  };

  const handleConfirmHide = () => {
    if (pendingHideModId === null) return;
    ignoreMutation.mutate(pendingHideModId, {
      onSettled: () => setPendingHideModId(null),
    });
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
    if (favoriteByModId.has(modId)) {
      setPendingUnfavoriteModId(modId);
      return;
    }
    favoriteMutation.mutate(modId);
  };

  const handleConfirmUnfavorite = () => {
    if (pendingUnfavoriteModId === null) return;
    favoriteMutation.mutate(pendingUnfavoriteModId, {
      onSettled: () => setPendingUnfavoriteModId(null),
    });
  };

  const { regenerateSummary: handleRegenerateSummary, regeneratingSummaryIds } = useSummaryRegeneration({
    t,
    setStatus: setLastResult,
    primaryQueryKey: ["mods"],
    extraQueryKeys: [["favorites"]],
    refetch,
  });

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

    const jumpToPage = () => {
      const clamped = parseIntegerInput(pageInput, { min: 1, max: totalPages });
      if (clamped === null || clamped === undefined) {
        setPageInput(String(page));
        return;
      }
      if (clamped !== page) {
        setPage(clamped);
      } else {
        setPageInput(String(clamped));
      }
    };

    return (
      <div className="mt-8 flex flex-wrap items-center justify-center gap-2">
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
        <div className="ml-2 inline-flex items-center gap-2">
          <input
            type="number"
            min={1}
            max={totalPages}
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                jumpToPage();
              }
            }}
            className="h-9 w-24 rounded-md border border-slate-200 bg-white px-2 text-sm font-semibold text-slate-700 outline-none focus:border-blue-500 focus:ring-2 focus:ring-blue-100"
            aria-label={t("discover.pageJumpInputLabel")}
          />
          <Button type="button" variant="outline" size="sm" onClick={jumpToPage}>
            {t("discover.pageJumpAction")}
          </Button>
        </div>
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
              <div className="flex items-center gap-3">
                <Button
                  type="button"
                  onClick={() => setImportDialogOpen(true)}
                  className="h-12 rounded-lg bg-slate-900 px-4 text-white shadow-sm hover:bg-slate-800"
                >
                  <DownloadCloud size={17} />
                  <span className="ml-2">{t("discover.importGame")}</span>
                </Button>
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
            </div>

            <ModFilterPanel
              searchValue={searchText}
              searchLabel={t("discover.search")}
              searchPlaceholder={t("discover.searchPlaceholder")}
              closeAriaLabel={t("common.close")}
              onSearchChange={setSearchText}
              onSearchClear={() => {
                setSearchText("");
                setSearch("");
                setPage(1);
              }}
              fields={[
                {
                  key: "game",
                  label: t("discover.game"),
                  value: game,
                  onChange: (value) => {
                    setGame(value);
                    setPage(1);
                  },
                  icon: <Gamepad2 size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[320px]",
                  children: (
                    <>
                      <option value="">{t("discover.allGames")}</option>
                      {gameOptions.map((g) => (
                        <option key={g.value} value={g.value}>
                          {g.label} ({g.count})
                        </option>
                      ))}
                    </>
                  ),
                },
                {
                  key: "source",
                  label: t("discover.source"),
                  value: source,
                  onChange: (value) => {
                    setSource(value as ModSource | "");
                    setPage(1);
                  },
                  icon: <Database size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[320px]",
                  children: (
                    <>
                      <option value="">{t("discover.allSources")}</option>
                      <option value="nexusmods">{t("discover.sourceNexusmods")}</option>
                      <option value="loverslab">{t("discover.sourceLoverslab")}</option>
                    </>
                  ),
                },
                {
                  key: "sort",
                  label: t("discover.sortBy"),
                  value: sort,
                  onChange: (value) => {
                    setSort(value);
                    setPage(1);
                  },
                  icon: <Clock size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[210px]",
                  children: (
                    <>
                      {SORTS.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </>
                  ),
                },
                {
                  key: "adultPolicy",
                  label: t("discover.adultPolicy"),
                  value: adultPolicy,
                  onChange: (value) => {
                    setAdultPolicy(value as AdultPolicy);
                    setPage(1);
                  },
                  icon: <ShieldCheck size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[210px]",
                  children: (
                    <>
                      {ADULT_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </>
                  ),
                },
                {
                  key: "contentLanguage",
                  label: t("discover.contentLanguage"),
                  value: contentLanguage,
                  onChange: (value) => {
                    setContentLanguage(value);
                    setPage(1);
                  },
                  icon: <Languages size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[210px]",
                  children: (
                    <>
                      <option value="any">{t("discover.contentLanguageAny")}</option>
                      <option value="en">{t("discover.contentLanguageEn")}</option>
                      <option value="zh">{t("discover.contentLanguageZh")}</option>
                      <option value="ja">{t("discover.contentLanguageJa")}</option>
                      <option value="ko">{t("discover.contentLanguageKo")}</option>
                      <option value="ru">{t("discover.contentLanguageRu")}</option>
                    </>
                  ),
                },
                {
                  key: "summaryMode",
                  label: t("settings.summaryMode"),
                  value: summaryMode,
                  onChange: (value) => setSummaryMode(value as SummaryMode),
                  icon: <Languages size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[210px]",
                  children: (
                    <>
                      <option value="original">{t("summary.original")}</option>
                      <option value="translated">{t("summary.translated")}</option>
                      <option value="bilingual">{t("summary.bilingual")}</option>
                    </>
                  ),
                },
              ]}
            />

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

              <div className="flex flex-wrap items-center gap-3">
                <FilterSelect
                  inlineLabel={t("discover.pageSize")}
                  value={String(pageSize)}
                  onValueChange={(value) => {
                    const nextPageSize = parseWholeIntegerInput(value);
                    if (typeof nextPageSize !== "number" || !isPageSize(nextPageSize)) return;
                    setPageSize(nextPageSize);
                    savePageSize(nextPageSize);
                    setPage(1);
                  }}
                >
                  {PAGE_SIZE_OPTIONS.map((sizeOption) => (
                    <option key={sizeOption} value={sizeOption}>
                      {t("discover.pageSizeOption", { count: sizeOption })}
                    </option>
                  ))}
                </FilterSelect>
                <FilterButtonGroup
                  containerClassName="inline-flex rounded-lg border border-slate-200 bg-white p-1 shadow-sm"
                  items={[
                    {
                      key: "card",
                      label: (
                        <>
                          <LayoutGrid size={17} />
                          {t("discover.viewCard")}
                        </>
                      ),
                      active: viewMode === "card",
                      onClick: () => setViewMode("card"),
                    },
                    {
                      key: "list",
                      label: (
                        <>
                          <List size={17} />
                          {t("discover.viewList")}
                        </>
                      ),
                      active: viewMode === "list",
                      onClick: () => setViewMode("list"),
                    },
                  ]}
                />
                <FilterBarButton
                  type="button"
                  className="text-slate-700"
                  onClick={() => setIgnoredListOpen(true)}
                >
                  <EyeOff size={17} />
                  <span className="ml-2">{t("discover.hiddenList")}</span>
                </FilterBarButton>
              </div>
            </div>

            {isLoading ? (
              <div className={viewMode === "card" ? "grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5" : "space-y-3"}>
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
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4 2xl:grid-cols-5">
                    {data?.items.map((mod) => (
                      <ModCard
                        key={mod.id}
                        mod={mod}
                        isFavorited={favoriteByModId.has(mod.id)}
                        onToggleFavorite={() => handleToggleFavorite(mod.id)}
                        showBottomFavoriteAction={false}
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
                      const displayTitle = formatModTitle(mod, summaryMode);
                      return (
                        <Card key={mod.id}>
                          <CardContent className="py-3">
                            <div className="flex items-start justify-between gap-3">
                              <div className="min-w-0 flex-1 space-y-2">
                                <div className="flex flex-wrap items-center gap-2">
                                  <SourceBadge source={mod.source} />
                                  {isAdultContent(mod.adult_content) && (
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
                                  className="block truncate whitespace-pre-line text-base font-semibold text-gray-900 hover:text-blue-600"
                                  title={displayTitle}
                                >
                                  {displayTitle}
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
      {importDialogOpen && (
        <ModalShell
          open={importDialogOpen}
          onClose={() => !isImportingGame && setImportDialogOpen(false)}
          size="md"
          panelClassName="max-w-lg"
        >
          <ModalHeader
            title={t("discover.importGame")}
            subtitle={t("discover.importGameDomain")}
            onClose={!isImportingGame ? () => setImportDialogOpen(false) : undefined}
            closeAriaLabel={t("common.close")}
          />
            <FilterInput
              label={t("discover.importGameDomain")}
              value={importGameDomain}
              onValueChange={setImportGameDomain}
              icon={<DownloadCloud size={18} className="text-slate-500" />}
              placeholder={t("discover.importGamePlaceholder")}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  handleImportNexusGame();
                }
              }}
              className="placeholder:text-slate-400"
              fieldClassName="h-11 w-full rounded-lg border border-slate-200 bg-white py-2 text-sm font-semibold text-slate-700"
            />
            <div className="mt-5 flex justify-end gap-2">
              <Button
                type="button"
                variant="outline"
                onClick={() => setImportDialogOpen(false)}
                disabled={isImportingGame}
              >
                {t("common.cancel")}
              </Button>
              <Button
                type="button"
                onClick={handleImportNexusGame}
                disabled={isImportingGame}
                className="bg-slate-900 text-white hover:bg-slate-800"
              >
                {isImportingGame ? <Loader2 size={17} className="animate-spin" /> : <DownloadCloud size={17} />}
                <span className="ml-2">
                  {isImportingGame ? t("discover.importingGame") : t("discover.importGame")}
                </span>
              </Button>
            </div>
        </ModalShell>
      )}
      {pendingUnfavoriteModId !== null && (
        <ConfirmModal
          open
          onClose={!favoriteMutation.isPending ? () => setPendingUnfavoriteModId(null) : undefined}
          onCancel={() => setPendingUnfavoriteModId(null)}
          onConfirm={handleConfirmUnfavorite}
          title={t("mod.unfavorite")}
          closeAriaLabel={t("common.close")}
          confirmLoading={favoriteMutation.isPending}
          confirmDisabled={favoriteMutation.isPending}
          confirmText={t("mod.unfavorite")}
          confirmChildren={
            <>
              {favoriteMutation.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <Heart size={14} className="fill-white text-white" />
              )}
              <span className="ml-1.5">{t("mod.unfavorite")}</span>
            </>
          }
          cancelText={t("common.cancel")}
        >
          {t("favorites.confirmRemove")}
        </ConfirmModal>
      )}
      {pendingHideModId !== null && (
        <ConfirmModal
          open
          onClose={!ignoreMutation.isPending ? () => setPendingHideModId(null) : undefined}
          onCancel={() => setPendingHideModId(null)}
          onConfirm={handleConfirmHide}
          title={t("mod.ignore")}
          closeAriaLabel={t("common.close")}
          confirmLoading={ignoreMutation.isPending}
          confirmDisabled={ignoreMutation.isPending}
          confirmText={t("mod.ignore")}
          confirmChildren={
            <>
              {ignoreMutation.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <EyeOff size={14} />
              )}
              <span className="ml-1.5">{t("mod.ignore")}</span>
            </>
          }
          cancelText={t("common.cancel")}
        >
          {t("discover.confirmHide")}
        </ConfirmModal>
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
  const summaryMode = useUIStore((s) => s.summaryMode);
  return (
    <ModalShell
      open
      onClose={onClose}
      size="lg"
      panelClassName="flex max-h-[82vh] flex-col overflow-hidden"
    >
      <ModalHeader
        title={t("discover.hiddenList")}
        subtitle={t("discover.hiddenListHint", { total })}
        onClose={onClose}
        closeAriaLabel={t("common.close")}
        className="mb-0 border-b border-gray-200 px-4 py-3"
      />
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
              {items.map((item) => {
                const displayTitle = formatModTitle(item, summaryMode);
                return (
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
                        className="mt-1 block truncate whitespace-pre-line text-sm font-semibold text-gray-900 hover:text-blue-600"
                        title={displayTitle}
                      >
                        {displayTitle}
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
                );
              })}
            </div>
          )}
      </div>
    </ModalShell>
  );
}

export default Discover;
