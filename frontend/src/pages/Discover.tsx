// 中文注释：实现 Discover 页面级交互和数据装配。

import React, { useState, useMemo, useEffect, useRef } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Play,
  Loader2,
  RefreshCw,
  ChevronDown,
  ChevronUp,
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
  Sparkles,
  Tags,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ModalHeader, ModalShell } from "@/components/ui/Modal";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { FilterBarButton, FilterButtonGroup, FilterInput, FilterSelect } from "@/components/ui/FilterControls";
import AppSidebar from "@/components/layout/AppSidebar";
import { ModCard } from "@/components/ModCard";
import { DiscoverPagination } from "@/components/DiscoverPagination";
import { ModIntroductionModal } from "@/components/modCard/ModIntroductionModal";
import { ModStatsLine } from "@/components/ModStatsLine";
import { SourceBadge } from "@/components/SourceBadge";
import { ModFilterPanel } from "@/components/ModFilterPanel";
import { Panel } from "@/components/ui/Panel";
import {
  fetchIgnoredMods,
  fetchModCategories,
  fetchModGames,
  fetchMods,
  generateModIntroduction,
  ignoreMod,
  unignoreMod,
} from "@/api/mods";
import { importNexusModsGame, pollJobRun, runDiscoveryAll } from "@/api/jobs";
import { favoriteByModId as mapFavoritesByModId, fetchFavoriteRefs } from "@/api/favorites";
import { useSummaryRegeneration } from "@/hooks/useSummaryRegeneration";
import { useFavoriteToggle } from "@/hooks/useFavoriteToggle";
import { useUIStore } from "@/stores/uiStore";
import { formatModSummary } from "@/utils/modSummary";
import { formatModTitle } from "@/utils/modTitle";
import { isAdultContent } from "@/utils/modAdult";
import { formatModCategory } from "@/utils/modCategory";
import { parseWholeIntegerInput } from "@/utils/numberInput";
import type { ModItem, ModSource, AdultPolicy, SummaryMode } from "@/types";

const PAGE_SIZE_OPTIONS = [20, 50, 80] as const;
type PageSize = (typeof PAGE_SIZE_OPTIONS)[number];
const DEFAULT_PAGE_SIZE: PageSize = 20;
const DISCOVER_PAGE_SIZE_STORAGE_KEY = "modWatcher.discover.pageSize";
type DiscoverViewMode = "card" | "list";

const discoverSourceBadgeClass: Record<ModSource, string> = {
  nexusmods:
    "border-cyan-300/70 bg-cyan-50 text-cyan-900 shadow-[0_8px_24px_rgba(8,145,178,0.12)]",
  loverslab:
    "border-sky-300/70 bg-sky-50 text-sky-900 shadow-[0_8px_24px_rgba(2,132,199,0.12)]",
};

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
    <Panel padding="none" className="overflow-hidden border-slate-200/80 bg-[#f8fbff] animate-pulse">
      <div className="aspect-[300/169] bg-slate-900" />
      <div className="space-y-3 p-4">
        <div className="h-4 w-3/4 rounded bg-slate-200" />
        <div className="flex gap-2">
          <div className="h-3 w-16 rounded bg-sky-100" />
          <div className="h-3 w-16 rounded bg-cyan-100" />
          <div className="h-3 w-20 rounded bg-slate-200" />
        </div>
        <div className="rounded-lg border border-slate-200 bg-white/70 p-3">
          <div className="h-3 w-full rounded bg-slate-200" />
          <div className="mt-2 h-3 w-2/3 rounded bg-slate-200" />
        </div>
        <div className="mt-2 h-8 rounded bg-slate-200" />
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
  const [category, setCategory] = useState("");
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
  const { data: categoryOptions = [] } = useQuery({
    queryKey: ["mod-categories"],
    queryFn: fetchModCategories,
  });
  const { data: favorites = [] } = useQuery({
    queryKey: ["favorites", "refs"],
    queryFn: fetchFavoriteRefs,
  });

  const favoriteByModId = useMemo(() => mapFavoritesByModId(favorites), [favorites]);

  const queryParams = useMemo(
    () => ({
      game: game || undefined,
      category: category || undefined,
      search: search || undefined,
      source: source || undefined,
      contentLanguage: contentLanguage === "any" ? undefined : contentLanguage,
      adultContent: adultPolicy,
      sortBy: sort,
      sortOrder: "desc" as const,
      offset,
      limit: pageSize,
    }),
    [adultPolicy, category, contentLanguage, game, offset, pageSize, search, sort, source]
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

  const synchronizeDiscoverData = () => {
    queryClient.invalidateQueries({ queryKey: ["mod-games"] });
    queryClient.invalidateQueries({ queryKey: ["mod-categories"] });
    refetch();
  };

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
      synchronizeDiscoverData();
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
      synchronizeDiscoverData();
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
      synchronizeDiscoverData();
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
      synchronizeDiscoverData();
      queryClient.invalidateQueries({ queryKey: ["mods", "ignored"] });
    },
  });

  const { favoriteMutation } = useFavoriteToggle({
    favoriteByModId,
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

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex h-screen">
        <AppSidebar active="discover" />

        <main className="relative flex-1 overflow-y-auto bg-slate-50">
          <div className="pointer-events-none absolute inset-x-0 top-0 h-64 bg-[radial-gradient(circle_at_18%_0%,rgba(14,165,233,0.12),transparent_34%),radial-gradient(circle_at_86%_8%,rgba(56,189,248,0.08),transparent_30%)]" />
          <div className="relative px-5 py-5 lg:px-7">
            <div className="mb-5 overflow-hidden rounded-xl border border-slate-200 bg-white p-4 shadow-[0_18px_42px_rgba(15,23,42,0.06)] md:p-5">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="min-w-0">
                  <div className="mb-2 flex items-center gap-2 text-[11px] font-semibold text-slate-500">
                    <span className="h-2 w-2 rounded-full bg-sky-500 shadow-[0_0_12px_rgba(14,165,233,0.45)]" />
                    <span>{t("nav.discover")}</span>
                    <span className="h-px w-10 bg-slate-200" />
                    <span>{updatedLabel}</span>
                  </div>
                  <h1 className="text-3xl font-bold tracking-normal text-slate-950">{t("discover.title")}</h1>
                  <p className="mt-2 max-w-3xl text-sm font-medium leading-6 text-slate-500">{t("discover.subtitle")}</p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  {source && (
                    <span className="inline-flex h-10 items-center gap-2 rounded-lg border border-cyan-200 bg-cyan-50 px-3 text-sm font-semibold text-cyan-800">
                      <Database size={16} />
                      {source}
                    </span>
                  )}
                  {game && (
                    <span className="inline-flex h-10 max-w-56 items-center gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 text-sm font-semibold text-amber-800">
                      <Gamepad2 size={16} />
                      <span className="truncate">{game}</span>
                    </span>
                  )}
                </div>
              </div>
              <div className="mt-5 flex flex-col gap-2 sm:flex-row sm:items-center">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setImportDialogOpen(true)}
                  className="h-11 rounded-lg border-sky-300 bg-white px-4 text-sm font-bold text-sky-800 shadow-sm hover:border-sky-400 hover:bg-sky-50 hover:text-sky-900"
                >
                  <DownloadCloud size={17} />
                  <span className="ml-2">{t("discover.importGame")}</span>
                </Button>
                <Button
                  onClick={handleRunDiscovery}
                  disabled={isRunning}
                  className="h-11 rounded-lg bg-sky-600 px-5 text-base font-bold text-white shadow-sm shadow-sky-200 hover:bg-sky-700"
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
              compact
              className="border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,0.06)]"
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
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[260px]",
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
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[220px]",
                  children: (
                    <>
                      <option value="">{t("discover.allSources")}</option>
                      <option value="nexusmods">{t("discover.sourceNexusmods")}</option>
                      <option value="loverslab">{t("discover.sourceLoverslab")}</option>
                    </>
                  ),
                },
                {
                  key: "category",
                  label: t("discover.category"),
                  value: category,
                  onChange: (value) => {
                    setCategory(value);
                    setPage(1);
                  },
                  icon: <Tags size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[260px]",
                  children: (
                    <>
                      <option value="">{t("discover.allCategories")}</option>
                      {categoryOptions.map((option) => (
                        <option key={option.value} value={option.value}>
                          {formatModCategory(option.label, t)} ({option.count})
                        </option>
                      ))}
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
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[180px]",
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
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[180px]",
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
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[180px]",
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
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[180px]",
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
              <p className="mb-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-2 text-sm font-semibold text-sky-800">
                {lastResult}
              </p>
            )}

            <div className="mb-4 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
                <span className="inline-flex items-center gap-2 font-bold text-sky-700">
                  <TrendingUp size={18} />
                  {t("discover.resultsCount", { count: data?.total ?? 0 })}
                </span>
                <span className="hidden h-5 w-px bg-slate-200 sm:block" />
                <span className="font-medium">{updatedLabel}</span>
                <button
                  type="button"
                  onClick={synchronizeDiscoverData}
                  className="inline-flex items-center rounded-md p-1 text-slate-500 transition hover:bg-slate-100 hover:text-sky-700"
                  title={t("discover.retry")}
                >
                  <RefreshCw size={17} />
                </button>
              </div>

              <div className="flex flex-wrap items-center gap-3">
                <FilterSelect
                  inlineLabel={t("discover.pageSize")}
                  inlineClassName="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 p-1 shadow-sm [&>span]:text-slate-600"
                  fieldClassName="border-slate-200 bg-white text-slate-700 focus:border-sky-500 focus:ring-sky-100"
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
                  containerClassName="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-1 shadow-sm"
                  activeClassName="bg-sky-100 text-sky-800 shadow-sm"
                  inactiveClassName="text-slate-600 hover:bg-white hover:text-slate-950"
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
                  className="border-slate-200 bg-white text-slate-700 hover:bg-slate-50 hover:text-slate-950"
                  onClick={() => setIgnoredListOpen(true)}
                >
                  <EyeOff size={17} />
                  <span className="ml-2">{t("discover.hiddenList")}</span>
                </FilterBarButton>
              </div>
            </div>

            {isLoading ? (
              <div className={viewMode === "card" ? "grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4" : "space-y-3"}>
                {Array.from({ length: 6 }).map((_, i) => (
                  <SkeletonCard key={i} />
                ))}
              </div>
            ) : isError ? (
              <div className="rounded-xl border border-rose-200 bg-rose-50 py-16 text-center">
                <p className="mb-4 text-rose-700">
                  {(error as Error)?.message || t("discover.loadFailed")}
                </p>
                <Button onClick={() => refetch()} className="bg-rose-600 text-white hover:bg-rose-700">
                  <RefreshCw size={16} />
                  <span className="ml-1.5">{t("discover.retry")}</span>
                </Button>
              </div>
            ) : data && data.items.length === 0 ? (
              <div className="rounded-xl border border-slate-200 bg-white py-16 text-center shadow-sm">
                <div className="mb-2 text-slate-300">
                  <Search size={48} className="mx-auto" />
                </div>
                <p className="text-sm text-slate-600">{t("discover.noMods")}</p>
                <p className="mt-1 text-xs text-slate-400">
                  {t("discover.configureHint")}
                </p>
              </div>
            ) : (
              <>
                {viewMode === "card" ? (
                  <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
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
                    {data?.items.map((mod) => (
                      <DiscoverListRow
                        key={mod.id}
                        mod={mod}
                        isFavorited={favoriteByModId.has(mod.id)}
                        summaryMode={summaryMode}
                        onToggleFavorite={() => handleToggleFavorite(mod.id)}
                        onIgnore={() => handleIgnore(mod.id)}
                        onRegenerateSummary={() => handleRegenerateSummary(mod.id)}
                        regeneratingSummary={regeneratingSummaryIds.has(mod.id)}
                        onGenerateIntroduction={() => handleGenerateIntroduction(mod.id)}
                        generatingIntroduction={generateIntroductionMutation.isPending && generateIntroductionMutation.variables === mod.id}
                      />
                    ))}
                  </div>
                )}
              <DiscoverPagination page={page} totalPages={totalPages} pageInput={pageInput} onPageInputChange={setPageInput} onPageChange={setPage} />
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
                className="bg-sky-600 text-white hover:bg-sky-700"
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

function DiscoverListRow({
  mod,
  isFavorited,
  summaryMode,
  onToggleFavorite,
  onIgnore,
  onRegenerateSummary,
  regeneratingSummary,
  onGenerateIntroduction,
  generatingIntroduction,
}: {
  mod: ModItem;
  isFavorited: boolean;
  summaryMode: SummaryMode;
  onToggleFavorite: () => void;
  onIgnore: () => void;
  onRegenerateSummary: () => void;
  regeneratingSummary: boolean;
  onGenerateIntroduction: () => Promise<string | undefined>;
  generatingIntroduction: boolean;
}) {
  const { t } = useTranslation();
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [introductionOpen, setIntroductionOpen] = useState(false);
  const [introduction, setIntroduction] = useState(mod.ai_introduction || "");
  const [introError, setIntroError] = useState("");
  const gameLabel = mod.game || mod.game_domain || "";
  const displayTitle = formatModTitle(mod, summaryMode);
  const summary = formatModSummary({
    original: mod.original_summary,
    translated: mod.translated_summary,
    mode: summaryMode,
    maxLength: 260,
  });
  const fullSummary = formatModSummary({
    original: mod.original_summary,
    translated: mod.translated_summary,
    mode: summaryMode,
  });
  const canToggleSummary = Boolean(fullSummary) && (
    summary !== fullSummary ||
    fullSummary.length > 160 ||
    fullSummary.includes("\n")
  );

  const handleOpenIntroduction = async () => {
    setIntroductionOpen(true);
    setIntroError("");
    if (introduction || mod.ai_introduction) {
      setIntroduction(introduction || mod.ai_introduction || "");
      return;
    }
    try {
      const content = await onGenerateIntroduction();
      setIntroduction(content || "");
    } catch (error) {
      setIntroError(error instanceof Error ? error.message : "Failed to generate introduction");
    }
  };

  return (
    <Card className="border-slate-200 bg-[#f8fbff] shadow-[0_12px_30px_rgba(15,23,42,0.07)]">
      <CardContent className="py-3">
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <SourceBadge source={mod.source} className={discoverSourceBadgeClass[mod.source]} />
            {isAdultContent(mod.adult_content) && (
              <span className="inline-flex items-center gap-1 rounded-md border border-rose-300 bg-rose-50 px-2 py-0.5 text-xs font-semibold text-rose-800">
                <ShieldCheck size={12} />
                NSFW
              </span>
            )}
            {gameLabel && (
              <span className="inline-flex max-w-64 items-center gap-1 rounded-md border border-slate-300 bg-white px-2 py-0.5 text-xs font-semibold text-slate-700">
                <Gamepad2 size={12} />
                <span className="truncate">{gameLabel}</span>
              </span>
            )}
          </div>

          <a
            href={mod.url}
            target="_blank"
            rel="noopener noreferrer"
            className="block truncate whitespace-pre-line text-base font-bold text-slate-950 hover:text-sky-700"
            title={displayTitle}
          >
            {displayTitle}
          </a>

          <ModStatsLine
            downloads={mod.downloads}
            endorsements={mod.endorsements}
            updatedAt={mod.updated_at_remote}
            className="font-semibold text-slate-500"
          />

          {summary && (
            <p className={`${summaryExpanded ? "" : "line-clamp-2"} whitespace-pre-line text-sm leading-6 text-slate-600`}>
              {summaryExpanded ? fullSummary || summary : summary}
            </p>
          )}

          <div className="flex flex-wrap items-center gap-2 border-t border-slate-200/70 pt-3">
            {canToggleSummary && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="border border-slate-200 bg-white/75 text-slate-700 hover:border-sky-200 hover:bg-sky-50 hover:text-sky-800"
                onClick={() => setSummaryExpanded((value) => !value)}
              >
                {summaryExpanded ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
                <span className="ml-1.5">{summaryExpanded ? t("mod.collapseSummary") : t("mod.expandSummary")}</span>
              </Button>
            )}
            <a href={mod.url} target="_blank" rel="noopener noreferrer">
              <Button size="sm" variant="ghost" className="border border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100">
                <ExternalLink size={14} />
                <span className="ml-1.5">{t("common.viewMod")}</span>
              </Button>
            </a>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="border border-slate-200 bg-white/75 text-slate-700 hover:bg-slate-100"
              onClick={onToggleFavorite}
            >
              <Heart size={14} className={isFavorited ? "fill-red-500 text-red-500" : ""} />
              <span className="ml-1.5">{t(isFavorited ? "mod.unfavorite" : "mod.favorite")}</span>
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="border border-slate-200 bg-white/75 text-slate-700 hover:bg-slate-100"
              onClick={onIgnore}
            >
              <EyeOff size={14} />
              <span className="ml-1.5">{t("mod.ignore")}</span>
            </Button>
            {summaryMode !== "original" && (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                className="border border-cyan-200 bg-cyan-50 text-cyan-800 hover:bg-cyan-100"
                onClick={onRegenerateSummary}
                disabled={regeneratingSummary}
              >
                <Languages size={14} />
                <span className="ml-1.5">{regeneratingSummary ? t("common.loading") : t("mod.regenerateSummary")}</span>
              </Button>
            )}
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="border border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"
              onClick={handleOpenIntroduction}
              disabled={generatingIntroduction}
            >
              <Sparkles size={14} />
              <span className="ml-1.5">{generatingIntroduction ? t("mod.generatingIntroduction") : t("mod.aiIntroduction")}</span>
            </Button>
          </div>
        </div>
      </CardContent>

      <ModIntroductionModal open={introductionOpen} title={displayTitle} introduction={introduction} fallbackIntroduction={mod.ai_introduction} error={introError} loading={generatingIntroduction} onClose={() => setIntroductionOpen(false)} />
    </Card>
  );
}

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
        className="mb-0 border-b border-slate-200 px-4 py-3"
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
                        className="mt-1 block truncate whitespace-pre-line text-sm font-semibold text-slate-900 hover:text-sky-700"
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
