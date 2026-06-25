import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Clock,
  Database,
  Gamepad2,
  Heart,
  Languages,
  RefreshCw,
  Search,
  Loader2,
  ShieldCheck,
  Trash2,
  TrendingUp,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import { ModCard } from "@/components/ModCard";
import AppSidebar from "@/components/layout/AppSidebar";
import { ModFilterPanel } from "@/components/ModFilterPanel";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import { Panel } from "@/components/ui/Panel";
import { FilterBarButton } from "@/components/ui/FilterControls";
import {
  fetchFavorites,
  updateFavorite,
  removeFavorite,
  checkUpdate,
} from "@/api/favorites";
import { generateModIntroduction } from "@/api/mods";
import { pollJobRun, runFavoriteCheck } from "@/api/jobs";
import { useSummaryRegeneration } from "@/hooks/useSummaryRegeneration";
import { useUIStore } from "@/stores/uiStore";
import { parseFavoriteCheckEntries } from "@/utils/favoriteCheckMetadata";
import { isAdultContent } from "@/utils/modAdult";
import { nonNegativeNumberValue } from "@/utils/numberInput";
import type { AdultPolicy, Favorite, ModSource, SummaryMode } from "@/types";

function SkeletonCard() {
  return (
    <Panel padding="none" className="overflow-hidden border-slate-200/80 bg-[#f8fbff] animate-pulse">
      <div className="aspect-[300/169] bg-slate-200" />
      <div className="space-y-3 p-4">
        <div className="h-4 w-3/4 rounded bg-slate-200" />
        <div className="h-3 w-1/2 rounded bg-slate-200" />
        <div className="rounded-lg border border-slate-200 bg-white/70 p-3">
          <div className="h-3 w-full rounded bg-slate-200" />
          <div className="mt-2 h-3 w-2/3 rounded bg-slate-200" />
        </div>
        <div className="grid grid-cols-2 gap-2 pt-2">
          <div className="h-9 rounded bg-slate-200" />
          <div className="h-9 rounded bg-slate-200" />
        </div>
      </div>
    </Panel>
  );
}

const Favorites: React.FC = () => {
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
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [checkingAllBusy, setCheckingAllBusy] = useState(false);
  const [checkingAllStatus, setCheckingAllStatus] = useState("");
  const [searchText, setSearchText] = useState("");
  const [game, setGame] = useState("");
  const [source, setSource] = useState<ModSource | "">("");
  const [sort, setSort] = useState("updated_at_remote");
  const [adultPolicy, setAdultPolicy] = useState<AdultPolicy>("include");
  const [contentLanguage, setContentLanguage] = useState("any");
  const [pendingRemoveId, setPendingRemoveId] = useState<number | null>(null);
  const checkAllRunRef = useRef(0);

  useEffect(() => {
    return () => {
      checkAllRunRef.current += 1;
    };
  }, []);

  const {
    data: favorites,
    isLoading,
    isError,
    error,
    refetch,
  } = useQuery({
    queryKey: ["favorites"],
    queryFn: fetchFavorites,
  });
  const gameOptions = useMemo(() => {
    const options = new Map<string, { value: string; label: string; count: number }>();
    for (const favorite of favorites ?? []) {
      const mod = favorite.mod;
      if (source && mod.source !== source) continue;
      const value = mod.game_domain === "loverslab" ? mod.game : mod.game_domain || mod.game;
      const label = mod.game || mod.game_domain;
      if (!value || !label) continue;
      const existing = options.get(value);
      if (existing) {
        existing.count += 1;
      } else {
        options.set(value, { value, label, count: 1 });
      }
    }
    return [...options.values()].sort((a, b) => b.count - a.count || a.label.localeCompare(b.label));
  }, [favorites, source]);

  const filteredFavorites = useMemo(() => {
    const matchesContentLanguage = (favorite: Favorite): boolean => {
      if (contentLanguage === "any") return true;
      const text = [
        favorite.mod.tags_json,
        favorite.mod.title,
        favorite.mod.original_summary,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();
      const keywordMap: Record<string, string[]> = {
        en: ["english", "en", "英文", "英语", "英語"],
        zh: ["chinese", "zh", "中文", "汉化", "漢化", "简体", "繁體", "简中", "繁中"],
        ja: ["japanese", "ja", "日文", "日语", "日本語"],
        ko: ["korean", "ko", "韩文", "韩语", "韓文", "韓語", "한글", "한국어"],
        ru: ["russian", "ru", "俄文", "俄语", "рус"],
      };
      return (keywordMap[contentLanguage] || []).some((keyword) => text.includes(keyword.toLowerCase()));
    };

    const scoreBySort = (favorite: Favorite): number | string => {
      const mod = favorite.mod;
      if (sort === "downloads") return nonNegativeNumberValue(mod.downloads) ?? 0;
      if (sort === "endorsements") return nonNegativeNumberValue(mod.endorsements) ?? 0;
      if (sort === "updated_at_remote") return mod.updated_at_remote || "";
      return mod.first_seen_at || "";
    };

    const term = searchText.trim().toLowerCase();
    const list = (favorites ?? []).filter((fav) => {
      const mod = fav.mod;
      if (source && mod.source !== source) return false;
      if (game && mod.game !== game && mod.game_domain !== game) return false;
      const adultContent = isAdultContent(mod.adult_content);
      if (adultPolicy === "exclude" && adultContent) return false;
      if (adultPolicy === "only" && !adultContent) return false;
      if (!matchesContentLanguage(fav)) return false;
      if (!term) return true;
      return [mod.title, mod.translated_title_zh, mod.original_summary, mod.translated_summary, fav.userNote]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term));
    });
    return list.sort((a, b) => {
      const av = scoreBySort(a);
      const bv = scoreBySort(b);
      if (typeof av === "number" && typeof bv === "number") return bv - av;
      return String(bv).localeCompare(String(av));
    });
  }, [adultPolicy, contentLanguage, favorites, game, searchText, sort, source]);

  const toggleMutation = useMutation({
    mutationFn: ({ id, data }: { id: number; data: Partial<Favorite> }) =>
      updateFavorite(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: number) => removeFavorite(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
    },
  });

  const generateIntroductionMutation = useMutation({
    mutationFn: generateModIntroduction,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
    },
  });

  const checkAllMutation = useMutation({
    mutationFn: runFavoriteCheck,
  });

  const handleGenerateIntroduction = async (modId: number) => {
    const result = await generateIntroductionMutation.mutateAsync(modId);
    return result.content;
  };

  const { regenerateSummary: handleRegenerateSummary, regeneratingSummaryIds } = useSummaryRegeneration({
    t,
    setStatus: setCheckingAllStatus,
    primaryQueryKey: ["favorites"],
    extraQueryKeys: [["mods"]],
    refetch,
  });

  const handleToggleTracking = (id: number, enabled: boolean) => {
    toggleMutation.mutate({ id, data: { trackingEnabled: enabled } });
  };

  const handleToggleNotify = (id: number, enabled: boolean) => {
    toggleMutation.mutate({ id, data: { notifyOnUpdate: enabled } });
  };

  const handleCheckUpdate = async (id: number) => {
    setCheckingId(id);
    try {
      const result = await checkUpdate(id);
      if (result.updateDetected) {
        alert(
          t("favorites.updateDetected", {
            version: result.updateEvent?.newVersion ?? t("common.unknown"),
            notification: result.notificationSent ? t("favorites.notificationSent") : t("favorites.notificationSkipped"),
          })
        );
      } else {
        alert(t("favorites.noUpdateDetected", {
          checkedAt: result.lastCheckedAt ?? t("common.unknown"),
        }));
      }
      refetch();
    } catch (e) {
      alert(
        t("favorites.checkUpdateFailed", {
          error: e instanceof Error ? e.message : t("common.unknown"),
        })
      );
    } finally {
      setCheckingId(null);
    }
  };

  const handleCheckAllUpdates = async () => {
    const runId = checkAllRunRef.current + 1;
    checkAllRunRef.current = runId;
    const isCurrentRun = () => checkAllRunRef.current === runId;
    setCheckingAllBusy(true);
    setCheckingAllStatus("");
    try {
      const result = await checkAllMutation.mutateAsync();
      if (!isCurrentRun()) return;
      setCheckingAllStatus(t("favorites.checkAllQueued", { jobId: result.job_id }));
      const pollResult = await pollJobRun(result.job_id, {
        isActive: isCurrentRun,
        onRunning: () => {
          setCheckingAllStatus(t("favorites.checkAllRunning", { jobId: result.job_id }));
        },
      });
      if (pollResult.status === "cancelled") return;
      if (pollResult.status === "timeout") {
        setCheckingAllStatus(t("favorites.checkAllTimeout"));
        return;
      }
      const job = pollResult.job;
      if (job.status === "failed") {
        setCheckingAllStatus(t("favorites.checkAllFailed", { error: job.error_message || "job failed" }));
        return;
      }
      const entries = parseFavoriteCheckEntries(job.metadata_json);
      const failed = entries.filter((entry) => entry.error).length;
      const notified = entries.filter((entry) => entry.notification_sent).length;
      const updatedTitles = entries
        .filter((entry) => entry.update_detected)
        .map((entry) => entry.title || `#${entry.favorite_id}`)
        .slice(0, 3)
        .join(", ");
      setCheckingAllStatus(t("favorites.checkAllDoneDetailed", {
        scanned: job.items_scanned,
        matched: job.items_matched,
        failed,
        notified,
        updated: updatedTitles || t("favorites.none"),
      }));
      queryClient.invalidateQueries({ queryKey: ["favorites"] });
      queryClient.invalidateQueries({ queryKey: ["updates"] });
    } catch (e) {
      if (!isCurrentRun()) return;
      setCheckingAllStatus(t("favorites.checkUpdateFailed", {
        error: e instanceof Error ? e.message : t("common.unknown"),
      }));
    } finally {
      if (isCurrentRun()) {
        setCheckingAllBusy(false);
      }
    }
  };

  const handleRemove = (id: number) => {
    setPendingRemoveId(id);
  };

  const handleConfirmRemove = () => {
    if (pendingRemoveId === null) return;
    removeMutation.mutate(pendingRemoveId, {
      onSettled: () => {
        setPendingRemoveId(null);
      },
    });
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex h-screen">
        <AppSidebar active="favorites" />

        <main className="flex-1 overflow-y-auto">
          <div className="px-6 py-6 lg:px-8">
            <div className="mb-7 flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
              <div>
                <h1 className="text-3xl font-bold tracking-normal text-slate-950">
                  {t("favorites.title")}
                </h1>
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <FilterBarButton
                  height="h12"
                  onClick={handleCheckAllUpdates}
                  disabled={checkingAllBusy || checkAllMutation.isPending || !favorites || favorites.length === 0}
                >
                  {checkingAllBusy || checkAllMutation.isPending ? (
                    <Loader2 size={18} className="animate-spin" />
                  ) : (
                    <RefreshCw size={18} />
                  )}
                  <span className="ml-2">{t("favorites.checkAllUpdates")}</span>
                </FilterBarButton>
                <FilterBarButton
                  height="h12"
                  onClick={() => refetch()}
                >
                  <RefreshCw size={18} />
                  <span className="ml-2">{t("common.refresh") || "Refresh"}</span>
                </FilterBarButton>
              </div>
            </div>

            {checkingAllStatus && (
              <p className="mb-4 rounded-lg border border-sky-200 bg-sky-50 px-4 py-2 text-sm font-semibold text-sky-800">
                {checkingAllStatus}
              </p>
            )}

            <ModFilterPanel
              compact
              className="border-slate-200 bg-white shadow-[0_12px_34px_rgba(15,23,42,0.06)]"
              searchValue={searchText}
              searchLabel={t("discover.search")}
              searchPlaceholder={t("favorites.searchPlaceholder")}
              closeAriaLabel={t("common.close")}
              onSearchChange={setSearchText}
              onSearchClear={() => {
                setSearchText("");
              }}
              fields={[
                {
                  key: "game",
                  label: t("discover.game"),
                  value: game,
                  onChange: (value) => setGame(value),
                  icon: <Gamepad2 size={18} />,
                  className: "w-full md:w-[calc(50%-0.375rem)] xl:w-[260px]",
                  children: (
                    <>
                      <option value="">{t("discover.allGames")}</option>
                      {gameOptions.map((g) => (
                        <option key={g.value} value={g.value}>{g.label} ({g.count})</option>
                      ))}
                    </>
                  ),
                },
                {
                  key: "source",
                  label: t("discover.source"),
                  value: source,
                  onChange: (value) => setSource(value as ModSource | ""),
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
                  key: "sort",
                  label: t("discover.sortBy"),
                  value: sort,
                  onChange: (value) => setSort(value),
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
                  onChange: (value) => setAdultPolicy(value as AdultPolicy),
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
                  onChange: (value) => setContentLanguage(value),
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

            <div className="mb-4 flex flex-col gap-3 rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm sm:flex-row sm:items-center sm:justify-between">
              <div className="flex flex-wrap items-center gap-3 text-sm text-slate-500">
                <span className="inline-flex items-center gap-2 font-bold text-sky-700">
                  <TrendingUp size={18} />
                  {t("discover.resultsCount", { count: filteredFavorites.length })}
                </span>
                <span className="hidden h-5 w-px bg-slate-200 sm:block" />
                <span className="font-medium">{isLoading ? t("common.loading") : t("discover.listLoaded")}</span>
                <button
                  type="button"
                  onClick={() => refetch()}
                  className="inline-flex items-center rounded-md p-1 text-slate-500 hover:bg-slate-100 hover:text-sky-700"
                  title={t("common.refresh") || "Refresh"}
                >
                  <RefreshCw size={17} />
                </button>
              </div>
            </div>

            {isLoading ? (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <SkeletonCard key={i} />
                ))}
              </div>
            ) : isError ? (
              <div className="py-16 text-center">
                <p className="text-red-500 mb-4">
                  {error instanceof Error ? error.message : t("common.error")}
                </p>
                <Button onClick={() => refetch()}>
                  <RefreshCw size={14} className="mr-2" />
                  {t("common.retry")}
                </Button>
              </div>
            ) : !favorites || favorites.length === 0 ? (
              <div className="py-16 text-center">
                <Heart size={48} className="mx-auto mb-4 text-slate-300" />
                <p className="text-sm text-slate-500">
                  {t("favorites.noFavorites") ||
                    "No favorites yet. Browse Discover page to add mods to favorites."}
                </p>
              </div>
            ) : filteredFavorites.length === 0 ? (
              <div className="py-16 text-center">
                <Search size={44} className="mx-auto mb-3 text-slate-300" />
                <p className="text-sm text-slate-500">{t("favorites.noFilterMatches")}</p>
              </div>
            ) : (
              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                {filteredFavorites.map((fav) => (
                  <ModCard
                    key={fav.id}
                    mod={fav.mod}
                    isFavorited
                    onToggleFavorite={() => handleRemove(fav.id)}
                    showBottomFavoriteAction={false}
                    onRegenerateSummary={() => handleRegenerateSummary(fav.mod.id)}
                    regeneratingSummary={regeneratingSummaryIds.has(fav.mod.id)}
                    onGenerateIntroduction={() => handleGenerateIntroduction(fav.mod.id)}
                    generatingIntroduction={generateIntroductionMutation.isPending && generateIntroductionMutation.variables === fav.mod.id}
                    footerContent={
                      <div className="space-y-3">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-slate-500">{t("mod.version")}</span>
                          <span className="font-medium text-slate-900">
                            {fav.lastKnownVersion || fav.mod.version || "-"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-xs text-slate-500">
                          <span>{t("favorites.lastChecked")}</span>
                          <span className="text-right text-slate-700">
                            {fav.lastCheckedAt ? new Date(fav.lastCheckedAt).toLocaleString() : t("favorites.neverChecked")}
                          </span>
                        </div>
                        <div className="grid grid-cols-2 gap-3">
                          <Switch
                            checked={fav.trackingEnabled}
                            onCheckedChange={(v) => handleToggleTracking(fav.id, v)}
                            label={t("favorites.tracking")}
                          />
                          <Switch
                            checked={fav.notifyOnUpdate}
                            onCheckedChange={(v) => handleToggleNotify(fav.id, v)}
                            disabled={!fav.trackingEnabled}
                            label={t("favorites.notify")}
                          />
                        </div>
                        <div className="grid grid-cols-2 gap-2 pt-1">
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => handleCheckUpdate(fav.id)}
                            disabled={checkingId === fav.id}
                          >
                            {checkingId === fav.id ? (
                              <Loader2 className="animate-spin h-3.5 w-3.5" />
                            ) : (
                              <RefreshCw size={13} />
                            )}
                            <span className="ml-1.5">{t("favorites.checkUpdate")}</span>
                          </Button>
                          <Button
                            size="sm"
                            variant="destructive"
                            onClick={() => handleRemove(fav.id)}
                            disabled={removeMutation.isPending}
                          >
                            <Trash2 size={13} />
                            <span className="ml-1.5">{t("common.delete")}</span>
                          </Button>
                        </div>
                      </div>
                    }
                  />
                ))}
              </div>
            )}
          </div>
        </main>
      </div>
      {pendingRemoveId !== null && (
        <ConfirmModal
          open
          onClose={!removeMutation.isPending ? () => setPendingRemoveId(null) : undefined}
          onCancel={() => setPendingRemoveId(null)}
          onConfirm={handleConfirmRemove}
          title={t("common.delete")}
          closeAriaLabel={t("common.close")}
          confirmLoading={removeMutation.isPending}
          confirmDisabled={removeMutation.isPending}
          confirmText={t("common.delete")}
          confirmChildren={
            <>
              {removeMutation.isPending ? (
                <Loader2 size={14} className="mr-1.5 animate-spin" />
              ) : (
                <Trash2 size={14} />
              )}
              <span className="ml-1.5">{t("common.delete")}</span>
            </>
          }
          cancelText={t("common.cancel")}
        >
          {t("favorites.confirmRemove") || "Remove this favorite?"}
        </ConfirmModal>
      )}
    </div>
  );
};

export default Favorites;
