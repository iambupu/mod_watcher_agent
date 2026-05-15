import React from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  LayoutDashboard,
  Search,
  Heart,
  Bell,
  Settings,
  SlidersHorizontal,
  Sparkles,
  RefreshCw,
  FileText,
} from "lucide-react";
import { Card, CardContent } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { fetchStats } from "@/api/stats";
import type { Stats } from "@/api/stats";

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

const Dashboard: React.FC = () => {
  const { t } = useTranslation();
  const { data: stats, isLoading, isError, refetch } = useQuery({
    queryKey: ["stats"],
    queryFn: fetchStats,
  });

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <aside className="w-64 bg-white border-r border-gray-200 flex flex-col">
          <div className="px-6 py-4 border-b border-gray-200 flex items-center gap-2">
            <img src="/mwlogo.png" alt="Mod Watcher" className="h-12 w-auto" />
            <span className="text-lg font-bold text-gray-900">Mod Watcher</span>
          </div>

          <nav className="flex-1 px-3 py-4 space-y-1">
            <NavLink href="/" icon={<LayoutDashboard size={18} />} label={t("nav.dashboard")} active />
            <NavLink href="/discover" icon={<Search size={18} />} label={t("nav.discover")} />
            <NavLink href="/favorites" icon={<Heart size={18} />} label={t("nav.favorites")} />
            <NavLink href="/updates" icon={<Bell size={18} />} label={t("nav.updates")} />
            <NavLink href="/rules" icon={<SlidersHorizontal size={18} />} label={t("nav.rules")} />
            <NavLink href="/logs" icon={<FileText size={18} />} label={t("nav.logs")} />
            <NavLink href="/settings" icon={<Settings size={18} />} label={t("nav.settings")} />
          </nav>

        </aside>

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
        </main>
      </div>
    </div>
  );
};

export default Dashboard;
