import React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Heart,
  Bell,
  SlidersHorizontal,
  Sparkles,
  RefreshCw,
  ExternalLink,
  Download,
  ThumbsUp,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import AppSidebar from "@/components/layout/AppSidebar";
import { fetchStats } from "@/api/stats";
import type { Stats } from "@/api/stats";
import { fetchMods } from "@/api/mods";
import type { ModItem } from "@/types";

interface StatCardConfig {
  icon: React.ReactNode;
  labelKey: string;
  valueKey: keyof Stats;
  color: string;
  bgColor: string;
}

const STAT_CARDS: StatCardConfig[] = [
  {
    icon: <LayoutDashboard size={20} />,
    labelKey: "dashboard.totalMods",
    valueKey: "total_mods",
    color: "text-blue-600",
    bgColor: "bg-blue-50",
  },
  {
    icon: <Sparkles size={20} />,
    labelKey: "dashboard.newModsThisWeek",
    valueKey: "new_mods_this_week",
    color: "text-green-600",
    bgColor: "bg-green-50",
  },
  {
    icon: <Heart size={20} />,
    labelKey: "dashboard.totalFavorites",
    valueKey: "total_favorites",
    color: "text-red-600",
    bgColor: "bg-red-50",
  },
  {
    icon: <SlidersHorizontal size={20} />,
    labelKey: "dashboard.watchRules",
    valueKey: "total_rules",
    color: "text-purple-600",
    bgColor: "bg-purple-50",
  },
  {
    icon: <Bell size={20} />,
    labelKey: "dashboard.unseenUpdates",
    valueKey: "unseen_updates",
    color: "text-orange-600",
    bgColor: "bg-orange-50",
  },
];

const StatCard: React.FC<{ config: StatCardConfig; value?: number; loading?: boolean }> = ({
  config,
  value,
  loading,
}) => {
  const { t } = useTranslation();

  if (loading) {
    return (
      <Card>
        <CardContent className="flex items-center gap-4 py-4">
          <div className="p-3 rounded-lg bg-gray-100 animate-pulse">
            <div className="w-5 h-5 bg-gray-200 rounded" />
          </div>
          <div className="flex-1 space-y-2">
            <div className="h-6 w-12 bg-gray-200 rounded animate-pulse" />
            <div className="h-4 w-20 bg-gray-200 rounded animate-pulse" />
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardContent className="flex items-center gap-4 py-4">
        <div className={`p-3 rounded-lg ${config.bgColor} ${config.color}`}>{config.icon}</div>
        <div>
          <p className="text-2xl font-bold text-gray-900">{value ?? 0}</p>
          <p className="text-sm text-gray-500">{t(config.labelKey)}</p>
        </div>
      </CardContent>
    </Card>
  );
};

function compactNumber(value?: number): string {
  if (value === undefined || value === null) return "0";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(value);
}

function pickSummary(mod: ModItem): string {
  return mod.translated_summary || mod.original_summary || "";
}

const RecommendedModCard: React.FC<{ mod: ModItem }> = ({ mod }) => {
  const { t } = useTranslation();
  const summary = pickSummary(mod);

  return (
    <a
      href={mod.url}
      target="_blank"
      rel="noopener noreferrer"
      className="group flex min-h-[150px] flex-col overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm transition hover:border-blue-200 hover:shadow-md"
    >
      <div className="flex gap-3 p-3">
        <div className="h-20 w-24 flex-shrink-0 overflow-hidden rounded-md bg-gray-100">
          {mod.thumbnail_url ? (
            <img src={mod.thumbnail_url} alt={mod.title} className="h-full w-full object-cover" loading="lazy" />
          ) : (
            <div className="flex h-full w-full items-center justify-center text-gray-300">
              <Sparkles size={24} />
            </div>
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start gap-2">
            <h4 className="line-clamp-2 text-sm font-semibold text-gray-900 group-hover:text-blue-700">
              {mod.title}
            </h4>
            <ExternalLink size={14} className="mt-0.5 flex-shrink-0 text-gray-400" />
          </div>
          <p className="mt-1 truncate text-xs text-gray-500">{mod.game || mod.game_domain || mod.source}</p>
          <div className="mt-2 flex flex-wrap items-center gap-3 text-xs text-gray-500">
            {mod.downloads !== undefined && mod.downloads !== null && (
              <span className="inline-flex items-center gap-1">
                <Download size={12} />
                {compactNumber(mod.downloads)}
              </span>
            )}
            {mod.endorsements !== undefined && mod.endorsements !== null && (
              <span className="inline-flex items-center gap-1">
                <ThumbsUp size={12} />
                {compactNumber(mod.endorsements)}
              </span>
            )}
          </div>
        </div>
      </div>
      <div className="border-t border-gray-100 px-3 py-2">
        <p className="line-clamp-3 text-xs leading-5 text-gray-600">
          {summary || t("dashboard.llmSummaryNoSummary")}
        </p>
      </div>
    </a>
  );
};

const Dashboard: React.FC = () => {
  const { t } = useTranslation();
  const { data: stats, isLoading, isError, refetch } = useQuery({
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
    queryFn: () => fetchMods({ sortBy: "downloads", sortOrder: "desc", limit: 3 }),
  });
  const recommendedMods = recommendationData?.items ?? [];
  const summaryText = t("dashboard.llmSummaryBody", {
    count: recommendedMods.length,
    total: stats?.total_mods ?? 0,
    weekly: stats?.new_mods_this_week ?? 0,
  });

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <AppSidebar active="dashboard" />

        <main className="flex-1 overflow-y-auto p-6">
          <div className="mb-8">
            <h2 className="text-2xl font-bold text-gray-900">{t("dashboard.welcome")}</h2>
            <p className="text-sm text-gray-500 mt-1">{t("dashboard.welcomeDesc")}</p>
          </div>

          {isError ? (
            <Card>
              <CardContent className="flex flex-col items-center gap-3 py-8">
                <p className="text-sm text-gray-500">{t("dashboard.loadFailed")}</p>
                <Button variant="outline" size="sm" onClick={() => refetch()}>
                  <RefreshCw size={14} className="mr-1.5" />
                  {t("dashboard.retry")}
                </Button>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5 gap-4">
              {STAT_CARDS.map((card) => (
                <StatCard
                  key={card.valueKey}
                  config={card}
                  value={stats?.[card.valueKey]}
                  loading={isLoading}
                />
              ))}
            </div>
          )}

          <section className="mt-6 space-y-4">
            <div>
              <div className="flex items-center gap-2">
                <Sparkles size={18} className="text-blue-600" />
                <h3 className="text-lg font-semibold text-gray-900">{t("dashboard.llmSummaryTitle")}</h3>
              </div>
              <p className="mt-1 text-sm text-gray-500">{t("dashboard.llmSummarySubtitle")}</p>
            </div>

            <Card>
              <CardContent className="space-y-4 py-5">
                <div className="rounded-lg border border-blue-100 bg-blue-50 px-4 py-3">
                  <p className="text-sm font-medium text-blue-900">{t("dashboard.llmSummaryExplanation")}</p>
                  <p className="mt-1 text-sm leading-6 text-blue-800">{summaryText}</p>
                </div>

                <div>
                  <div className="mb-3 flex items-center justify-between gap-3">
                    <h4 className="text-sm font-semibold text-gray-900">{t("dashboard.recommendedMods")}</h4>
                    {recommendationsError && (
                      <Button variant="outline" size="sm" onClick={() => refetchRecommendations()}>
                        <RefreshCw size={14} className="mr-1.5" />
                        {t("dashboard.retry")}
                      </Button>
                    )}
                  </div>

                  {recommendationsLoading ? (
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                      {[0, 1, 2].map((item) => (
                        <div key={item} className="h-40 rounded-lg border border-gray-200 bg-white p-3">
                          <div className="flex gap-3">
                            <div className="h-20 w-24 animate-pulse rounded-md bg-gray-100" />
                            <div className="flex-1 space-y-2">
                              <div className="h-4 w-3/4 animate-pulse rounded bg-gray-100" />
                              <div className="h-3 w-1/2 animate-pulse rounded bg-gray-100" />
                              <div className="h-3 w-2/3 animate-pulse rounded bg-gray-100" />
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : recommendedMods.length > 0 ? (
                    <div className="grid grid-cols-1 gap-3 lg:grid-cols-3">
                      {recommendedMods.map((mod) => (
                        <RecommendedModCard key={mod.id} mod={mod} />
                      ))}
                    </div>
                  ) : (
                    <div className="rounded-lg border border-dashed border-gray-200 bg-gray-50 px-4 py-6 text-center">
                      <p className="text-sm text-gray-500">{t("dashboard.noRecommendations")}</p>
                    </div>
                  )}
                </div>
              </CardContent>
            </Card>
          </section>
        </main>
      </div>
    </div>
  );
};

export default Dashboard;
