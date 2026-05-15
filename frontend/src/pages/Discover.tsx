import React, { useState, useMemo } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Search,
  LayoutDashboard,
  Heart,
  Bell,
  Settings,
  SlidersHorizontal,
  Play,
  Loader2,
  RefreshCw,
  ChevronLeft,
  ChevronRight,
  FileText,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { ModCard } from "@/components/ModCard";
import { fetchModGames, fetchMods, generateModIntroduction, ignoreMod, regenerateModSummary } from "@/api/mods";
import { fetchJobRun, runDiscoveryAll } from "@/api/jobs";
import { addFavorite, fetchFavorites, removeFavorite } from "@/api/favorites";
import { useUIStore } from "@/stores/uiStore";
import type { Favorite, ModSource, AdultPolicy, SummaryMode } from "@/types";

const NavLink: React.FC<{ href: string; icon: React.ReactNode; label: string; active?: boolean }> = ({
  href,
  icon,
  label,
  active,
}) => (
  <a
    href={href}
    className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      active ? "bg-blue-50 text-blue-700" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
    }`}
  >
    {icon}
    {label}
  </a>
);

const PAGE_SIZE = 24;

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden animate-pulse">
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

const Discover: React.FC = () => {
  const { t } = useTranslation();

  const SORTS = [
    { value: "updated_at_remote", label: t("discover.sortNewest") },
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
  const [source, setSource] = useState<ModSource | "">("");
  const [sort, setSort] = useState("updated_at_remote");
  const [adultPolicy, setAdultPolicy] = useState<AdultPolicy>("exclude");
  const [page, setPage] = useState(1);
  const [isRunning, setIsRunning] = useState(false);
  const [lastResult, setLastResult] = useState("");

  const offset = (page - 1) * PAGE_SIZE;

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
      source: source || undefined,
      adultContent: adultPolicy,
      sortBy: sort,
      sortOrder: "desc" as const,
      offset,
      limit: PAGE_SIZE,
    }),
    [adultPolicy, game, offset, sort, source]
  );

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["mods", queryParams],
    queryFn: () => fetchMods(queryParams),
    refetchInterval: summaryMode === "original" ? false : 15000,
  });

  const totalPages = data ? Math.ceil(data.total / PAGE_SIZE) : 0;

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
    setIsRunning(true);
    setLastResult("");
    try {
      const result = await runDiscoveryAll();
      setLastResult(`Queued job #${result.job_id}`);
      for (let i = 0; i < 60; i += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const job = await fetchJobRun(result.job_id);
        if (job.status === "queued" || job.status === "running") {
          setLastResult(`Job #${result.job_id} ${job.status}`);
          continue;
        }
        if (job.status === "failed") {
          setLastResult(`Error: ${job.error_message || "job failed"}`);
          return;
        }
        setLastResult(`Found ${job.items_matched} new mods`);
        refetch();
        return;
      }
    } catch (e) {
      setLastResult(`Error: ${(e as Error).message}`);
    } finally {
      setIsRunning(false);
    }
  };

  const ignoreMutation = useMutation({
    mutationFn: ignoreMod,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mods"] });
    },
  });

  const handleIgnore = (modId: number) => {
    ignoreMutation.mutate(modId);
  };

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
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mods"] });
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["mods"] }), 5000);
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
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center gap-2">
            <img src="/mwlogo.png" alt="Mod Watcher" className="h-12 w-auto" />
            <span className="text-lg font-bold text-gray-900">Mod Watcher</span>
          </div>
          <nav className="flex-1 px-3 py-4 space-y-1">
            <NavLink href="/" icon={<LayoutDashboard size={18} />} label={t("nav.dashboard")} />
            <NavLink href="/discover" icon={<Search size={18} />} label={t("nav.discover")} active />
            <NavLink href="/favorites" icon={<Heart size={18} />} label={t("nav.favorites")} />
            <NavLink href="/updates" icon={<Bell size={18} />} label={t("nav.updates")} />
            <NavLink href="/rules" icon={<SlidersHorizontal size={18} />} label={t("nav.rules")} />
            <NavLink href="/logs" icon={<FileText size={18} />} label={t("nav.logs")} />
            <NavLink href="/settings" icon={<Settings size={18} />} label={t("nav.settings")} />
          </nav>
        </aside>

        <main className="flex-1 overflow-y-auto">
          <div className="sticky top-0 z-10 bg-white/80 backdrop-blur-sm border-b border-gray-200 px-6 py-3 flex items-center justify-between">
            <h2 className="text-xl font-bold text-gray-900">{t("discover.title")}</h2>
            <Button onClick={handleRunDiscovery} disabled={isRunning}>
              {isRunning ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )}
              <span className="ml-1.5">
                {isRunning ? t("discover.running") : t("discover.runDiscovery")}
              </span>
            </Button>
          </div>

          <div className="p-6">
            <Card className="mb-6">
              <CardContent className="py-3">
                <div className="flex flex-wrap gap-3 items-end">
                  <div>
                    <label className="text-xs text-gray-500 block mb-1">{t("discover.game")}</label>
                    <select
                      value={game}
                      onChange={handleGameChange}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                    >
                      <option value="">{t("discover.allGames")}</option>
                      {gameOptions.map((g) => (
                        <option key={g.value} value={g.value}>
                          {g.label} ({g.count})
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-gray-500 block mb-1">{t("discover.source")}</label>
                    <select
                      value={source}
                      onChange={handleSourceChange}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                    >
                      <option value="">{t("discover.allSources")}</option>
                      <option value="nexusmods">{t("discover.sourceNexusmods")}</option>
                      <option value="loverslab">{t("discover.sourceLoverslab")}</option>
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-gray-500 block mb-1">{t("discover.sortBy")}</label>
                    <select
                      value={sort}
                      onChange={handleSortChange}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                    >
                      {SORTS.map((s) => (
                        <option key={s.value} value={s.value}>
                          {s.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-gray-500 block mb-1">{t("discover.adultPolicy")}</label>
                    <select
                      value={adultPolicy}
                      onChange={handleAdultChange}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                    >
                      {ADULT_OPTIONS.map((o) => (
                        <option key={o.value} value={o.value}>
                          {o.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="text-xs text-gray-500 block mb-1">{t("settings.summaryMode")}</label>
                    <select
                      value={summaryMode}
                      onChange={(e) => setSummaryMode(e.target.value as SummaryMode)}
                      className="rounded-md border border-gray-300 px-3 py-2 text-sm bg-white"
                    >
                      <option value="original">{t("summary.original")}</option>
                      <option value="translated">{t("summary.translated")}</option>
                      <option value="bilingual">{t("summary.bilingual")}</option>
                    </select>
                  </div>
                </div>
              </CardContent>
            </Card>

            {lastResult && (
              <p className="text-sm text-muted-foreground mb-4">{lastResult}</p>
            )}

            {isLoading ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
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
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {data?.items.map((mod) => (
                    <ModCard
                      key={mod.id}
                      mod={mod}
                      isFavorited={favoriteByModId.has(mod.id)}
                      onToggleFavorite={() => handleToggleFavorite(mod.id)}
                      onIgnore={() => handleIgnore(mod.id)}
                      onRegenerateSummary={() => handleRegenerateSummary(mod.id)}
                      regeneratingSummary={regenerateSummaryMutation.isPending && regenerateSummaryMutation.variables === mod.id}
                      onGenerateIntroduction={() => handleGenerateIntroduction(mod.id)}
                      generatingIntroduction={generateIntroductionMutation.isPending && generateIntroductionMutation.variables === mod.id}
                    />
                  ))}
                </div>
                {renderPagination()}
              </>
            )}
          </div>
        </main>
      </div>
    </div>
  );
};

function getFavoriteModId(favorite: Favorite): number | undefined {
  const raw = favorite as Favorite & { mod_id?: number };
  return raw.mod_id ?? favorite.modId;
}

export default Discover;
