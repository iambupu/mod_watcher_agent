import React, { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Heart,
  RefreshCw,
  Search,
  LayoutDashboard,
  Bell,
  Settings,
  SlidersHorizontal,
  Loader2,
  FileText,
  Trash2,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Switch } from "@/components/ui/Switch";
import { ModCard } from "@/components/ModCard";
import {
  fetchFavorites,
  updateFavorite,
  removeFavorite,
  checkUpdate,
} from "@/api/favorites";
import { fetchModGames, generateModIntroduction } from "@/api/mods";
import { useUIStore } from "@/stores/uiStore";
import type { Favorite, ModSource, SummaryMode } from "@/types";

const NavLink: React.FC<{
  href: string;
  icon: React.ReactNode;
  label: string;
  active?: boolean;
}> = ({ href, icon, label, active }) => (
  <a
    href={href}
    className={`flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors ${
      active
        ? "bg-blue-50 text-blue-700"
        : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
    }`}
  >
    {icon}
    {label}
  </a>
);

function SkeletonCard() {
  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden animate-pulse">
      <div className="aspect-[300/169] bg-gray-200" />
      <div className="p-4 space-y-3">
        <div className="h-4 bg-gray-200 rounded w-3/4" />
        <div className="h-3 bg-gray-200 rounded w-1/2" />
        <div className="h-3 bg-gray-200 rounded w-full" />
        <div className="h-3 bg-gray-200 rounded w-2/3" />
        <div className="grid grid-cols-2 gap-2 pt-2">
          <div className="h-9 bg-gray-200 rounded" />
          <div className="h-9 bg-gray-200 rounded" />
        </div>
      </div>
    </div>
  );
}

const Favorites: React.FC = () => {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { summaryMode, setSummaryMode } = useUIStore();
  const [checkingId, setCheckingId] = useState<number | null>(null);
  const [searchText, setSearchText] = useState("");
  const [game, setGame] = useState("");
  const [source, setSource] = useState<ModSource | "">("");

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
  const { data: gameOptions = [] } = useQuery({
    queryKey: ["mod-games"],
    queryFn: fetchModGames,
  });

  const filteredFavorites = useMemo(() => {
    const term = searchText.trim().toLowerCase();
    return (favorites ?? []).filter((fav) => {
      const mod = fav.mod;
      if (source && mod.source !== source) return false;
      if (game && mod.game !== game && mod.game_domain !== game) return false;
      if (!term) return true;
      return [mod.title, mod.original_summary, mod.translated_summary, fav.userNote]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(term));
    });
  }, [favorites, game, searchText, source]);

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

  const handleGenerateIntroduction = async (modId: number) => {
    const result = await generateIntroductionMutation.mutateAsync(modId);
    return result.content;
  };

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
      if (result.update_detected) {
        alert(
          t("favorites.updateDetected", {
            version: result.update_event?.newVersion ?? t("common.unknown"),
          })
        );
      } else {
        alert(t("favorites.noUpdateDetected"));
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

  const handleRemove = (id: number) => {
    if (window.confirm(t("favorites.confirmRemove") || "Remove this favorite?")) {
      removeMutation.mutate(id);
    }
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
            <NavLink href="/discover" icon={<Search size={18} />} label={t("nav.discover")} />
            <NavLink href="/favorites" icon={<Heart size={18} />} label={t("nav.favorites")} active />
            <NavLink href="/updates" icon={<Bell size={18} />} label={t("nav.updates")} />
            <NavLink href="/rules" icon={<SlidersHorizontal size={18} />} label={t("nav.rules")} />
            <NavLink href="/logs" icon={<FileText size={18} />} label={t("nav.logs")} />
            <NavLink href="/settings" icon={<Settings size={18} />} label={t("nav.settings")} />
          </nav>
        </aside>

        <main className="flex-1 overflow-y-auto p-6">
          <div className="flex items-center justify-between mb-6">
            <h2 className="text-2xl font-bold text-gray-900">
              {t("favorites.title")}
            </h2>
            <Button variant="outline" onClick={() => refetch()}>
              <RefreshCw size={14} />
              <span className="ml-1.5">{t("common.refresh") || "Refresh"}</span>
            </Button>
          </div>

          <Card className="mb-6">
            <CardContent className="py-3">
              <div className="flex flex-wrap items-end gap-3">
                <div>
                  <label className="mb-1 block text-xs text-gray-500">搜索</label>
                  <input
                    value={searchText}
                    onChange={(e) => setSearchText(e.target.value)}
                    className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm"
                    placeholder="标题或摘要"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-xs text-gray-500">游戏</label>
                  <select value={game} onChange={(e) => setGame(e.target.value)} className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm">
                    <option value="">全部游戏</option>
                    {gameOptions.map((g) => (
                      <option key={g.value} value={g.value}>{g.label} ({g.count})</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-gray-500">来源</label>
                  <select value={source} onChange={(e) => setSource(e.target.value as ModSource | "")} className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm">
                    <option value="">全部来源</option>
                    <option value="nexusmods">Nexus Mods</option>
                    <option value="loverslab">LoversLab</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-xs text-gray-500">{t("settings.summaryMode")}</label>
                  <select value={summaryMode} onChange={(e) => setSummaryMode(e.target.value as SummaryMode)} className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm">
                    <option value="original">{t("summary.original")}</option>
                    <option value="translated">{t("summary.translated")}</option>
                    <option value="bilingual">{t("summary.bilingual")}</option>
                  </select>
                </div>
              </div>
            </CardContent>
          </Card>

          {isLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {Array.from({ length: 6 }).map((_, i) => (
                <SkeletonCard key={i} />
              ))}
            </div>
          ) : isError ? (
            <Card>
              <CardContent className="py-12 text-center">
                <p className="text-red-500 mb-4">
                  {error instanceof Error ? error.message : t("common.error")}
                </p>
                <Button onClick={() => refetch()}>
                  <RefreshCw size={14} className="mr-2" />
                  {t("common.retry")}
                </Button>
              </CardContent>
            </Card>
          ) : !favorites || favorites.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Heart size={48} className="mx-auto text-gray-300 mb-4" />
                <p className="text-gray-500">
                  {t("favorites.noFavorites") ||
                    "No favorites yet. Browse Discover page to add mods to favorites."}
                </p>
              </CardContent>
            </Card>
          ) : filteredFavorites.length === 0 ? (
            <Card>
              <CardContent className="py-12 text-center">
                <Search size={44} className="mx-auto mb-3 text-gray-300" />
                <p className="text-sm text-gray-500">没有匹配筛选条件的收藏</p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
              {filteredFavorites.map((fav) => (
                <ModCard
                  key={fav.id}
                  mod={fav.mod}
                  isFavorited
                  onToggleFavorite={() => handleRemove(fav.id)}
                  onGenerateIntroduction={() => handleGenerateIntroduction(fav.mod.id)}
                  generatingIntroduction={generateIntroductionMutation.isPending && generateIntroductionMutation.variables === fav.mod.id}
                  footerContent={
                    <div className="space-y-3">
                      <div className="flex items-center justify-between text-sm">
                        <span className="text-gray-500">{t("mod.version")}</span>
                        <span className="font-medium text-gray-900">
                          {fav.lastKnownVersion || fav.mod.version || "-"}
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
        </main>
      </div>
    </div>
  );
};

export default Favorites;
