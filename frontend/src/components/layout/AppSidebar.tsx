import React, { lazy, Suspense, useState } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  Bell,
  BellRing,
  Bot,
  ChevronLeft,
  ChevronRight,
  Compass,
  FileText,
  Heart,
  LayoutDashboard,
  Settings,
  ListChecks,
  Info,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { useUIStore } from "@/stores/uiStore";
import { fetchUnreadCount } from "@/api/notifications";
import { ModalHeader, ModalShell } from "@/components/ui/Modal";

type NavKey = "agent" | "dashboard" | "discover" | "favorites" | "updates" | "rules" | "logs" | "settings";

interface AppSidebarProps {
  active: NavKey;
}

const navIconSize = 22;
const NotificationCenter = lazy(() =>
  import("@/components/NotificationCenter").then((module) => ({ default: module.NotificationCenter })),
);

const NAV_ITEMS: Array<{ key: NavKey; href: string; icon: React.ReactNode; labelKey: string }> = [
  { key: "agent", href: "/agent", icon: <Bot size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.agent" },
  { key: "dashboard", href: "/", icon: <LayoutDashboard size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.dashboard" },
  { key: "discover", href: "/discover", icon: <Compass size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.discover" },
  { key: "favorites", href: "/favorites", icon: <Heart size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.favorites" },
  { key: "updates", href: "/updates", icon: <Bell size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.updates" },
  { key: "rules", href: "/rules", icon: <ListChecks size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.rules" },
  { key: "logs", href: "/logs", icon: <FileText size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.logs" },
  { key: "settings", href: "/settings", icon: <Settings size={navIconSize} strokeWidth={2.15} />, labelKey: "nav.settings" },
];

const AppSidebar: React.FC<AppSidebarProps> = ({ active }) => {
  const { t } = useTranslation();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const [aboutOpen, setAboutOpen] = useState(false);
  const [notifyOpen, setNotifyOpen] = useState(false);
  const appVersion = import.meta.env.VITE_APP_VERSION || "0.2.2";

  const { data: unread } = useQuery({
    queryKey: ["notifications-unread-count"],
    queryFn: fetchUnreadCount,
    refetchInterval: 10000,
  });
  const unreadCount = unread?.count ?? 0;

  return (
    <aside className={`${sidebarOpen ? "w-60" : "w-20"} relative flex h-screen flex-col border-r border-slate-200 bg-[#f8fbff] shadow-[8px_0_30px_rgba(15,23,42,0.04)] transition-all duration-150`}>
      <button
        type="button"
        onClick={toggleSidebar}
        onMouseUp={(event) => event.currentTarget.blur()}
        className="absolute right-2 top-1/2 z-20 inline-flex h-12 w-5 -translate-y-1/2 items-center justify-center rounded-md bg-transparent text-slate-400 opacity-0 transition-[background-color,color,opacity] duration-150 hover:bg-slate-100/70 hover:text-slate-600 hover:opacity-100 active:bg-slate-100 focus:outline-none focus-visible:bg-slate-100 focus-visible:text-sky-700 focus-visible:opacity-100 focus-visible:ring-1 focus-visible:ring-inset focus-visible:ring-sky-200"
        title={sidebarOpen ? t("settings.hideSidebar") : t("settings.showSidebar")}
        aria-label={sidebarOpen ? t("settings.hideSidebar") : t("settings.showSidebar")}
      >
        {sidebarOpen ? <ChevronLeft size={15} strokeWidth={2.35} /> : <ChevronRight size={15} strokeWidth={2.35} />}
      </button>
      <div className={`border-b border-slate-100 py-4 ${sidebarOpen ? "px-3" : "px-2"}`}>
        <div className="relative">
          <div className={`flex items-center rounded-2xl border border-slate-200 bg-white shadow-[0_12px_30px_rgba(15,23,42,0.07)] ${
            sidebarOpen ? "gap-3 px-3 py-3 pr-2" : "justify-center px-2 py-3"
          }`}>
            <img
              src="/mwlogo.png"
              alt="Mod Watcher"
              className={`${sidebarOpen ? "h-12" : "h-9"} w-auto shrink-0 rounded-xl border border-slate-100 bg-white shadow-sm`}
            />
            {sidebarOpen && (
              <span className="min-w-0 flex-1 truncate text-lg font-bold tracking-normal text-slate-950">
                {t("nav.brand")}
              </span>
            )}
          </div>
        </div>
      </div>

      <nav className={`flex-1 space-y-2 py-6 ${sidebarOpen ? "pl-3 pr-10" : "px-2"}`}>
        {NAV_ITEMS.map((item) => {
          const isActive = item.key === active;
          return (
            <Link
              key={item.key}
              to={item.href}
              title={t(item.labelKey)}
              className={`relative flex min-h-[52px] items-center overflow-hidden rounded-xl text-base font-bold transition-all ${
                sidebarOpen ? "gap-4 px-5 py-3" : "justify-center px-2 py-3"
                } ${
                isActive
                  ? "bg-sky-50 text-sky-800 shadow-[0_10px_24px_rgba(14,165,233,0.10)] ring-1 ring-sky-100"
                  : "text-slate-600 hover:bg-slate-50 hover:text-slate-950"
              }`}
            >
              {isActive && (
                <span className="absolute left-0 top-2 bottom-2 w-[3px] rounded-r-full bg-sky-600" />
              )}
              <span className={`flex h-7 w-7 items-center justify-center ${isActive ? "text-sky-700" : "text-slate-500"}`}>
                {item.icon}
              </span>
              {sidebarOpen && <span className="truncate leading-6">{t(item.labelKey)}</span>}
            </Link>
          );
        })}
      </nav>
      <div className={`mx-3 mb-5 border-t border-slate-200 pt-7 flex flex-col gap-2 ${sidebarOpen ? "px-0" : "mx-2"}`}>
        <button
          type="button"
          onClick={() => setNotifyOpen(true)}
          className={`relative flex min-h-[50px] w-full items-center rounded-xl text-base font-bold text-slate-600 transition-all hover:bg-slate-50 hover:text-slate-950 ${
            sidebarOpen ? "gap-4 px-4 py-3" : "justify-center px-2 py-3"
          }`}
          title={t("notifications.title")}
        >
          <span className="flex h-7 w-7 items-center justify-center text-slate-500">
            {unreadCount > 0 ? <BellRing size={navIconSize} strokeWidth={2.15} /> : <Bell size={navIconSize} strokeWidth={2.15} />}
          </span>
          {sidebarOpen && <span className="truncate leading-6">{t("notifications.title")}</span>}
          {unreadCount > 0 && (
            <span className={sidebarOpen ? "ml-auto" : "absolute -top-1 -right-1"}>
              <span className="inline-flex h-7 min-w-7 items-center justify-center rounded-full bg-red-500 px-2 text-sm font-bold leading-none text-white shadow-[0_8px_18px_rgba(239,68,68,0.28)]">
                {unreadCount > 99 ? "99+" : unreadCount}
              </span>
            </span>
          )}
        </button>
        <button
          type="button"
          onClick={() => setAboutOpen(true)}
          className={`flex min-h-[50px] w-full items-center rounded-xl text-base font-bold text-slate-600 transition-all hover:bg-slate-50 hover:text-slate-950 ${
            sidebarOpen ? "gap-4 px-4 py-3" : "justify-center px-2 py-3"
          }`}
          title={t("about.title")}
        >
          <span className="flex h-7 w-7 items-center justify-center text-slate-500">
            <Info size={navIconSize} strokeWidth={2.15} />
          </span>
          {sidebarOpen && <span className="truncate leading-6">{t("about.title")}</span>}
        </button>
      </div>
      {notifyOpen && (
        <Suspense fallback={null}>
          <NotificationCenter open={notifyOpen} onClose={() => setNotifyOpen(false)} />
        </Suspense>
      )}
      {aboutOpen && (
        <ModalShell
          open={aboutOpen}
          onClose={() => setAboutOpen(false)}
          size="drawer-right"
          panelClassName="flex max-h-[calc(100vh-2rem)] flex-col overflow-hidden rounded-xl"
        >
          <ModalHeader
            title="Mod Watcher（模组巡望者）"
            onClose={() => setAboutOpen(false)}
            closeAriaLabel={t("common.close")}
            className="mb-0 shrink-0 border-b border-slate-200 px-4 py-3"
          />
            <div className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-4 text-sm text-gray-700">
              <div className="flex justify-center pb-1">
                <img src="/mwlogo.png" alt="Mod Watcher" className="h-40 w-auto" />
              </div>
              <div className="rounded-lg border border-sky-100 bg-gradient-to-r from-sky-50 to-cyan-50 px-3 py-2">
                <p className="mb-1 inline-flex items-center rounded-full bg-sky-600/10 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-sky-700">
                  {t("about.version")}
                </p>
                <p className="font-medium">v{appVersion}</p>
              </div>
              <div className="rounded-lg border border-sky-100 bg-gradient-to-r from-sky-50 to-white px-3 py-2">
                <p className="mb-2 inline-flex items-center rounded-full bg-sky-600/10 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-sky-700">
                  {t("about.changelog")}
                </p>
                <p className="break-words leading-6" style={{ whiteSpace: "pre-wrap" }}>{t("about.changelogText")}</p>
              </div>
              <div className="rounded-lg border border-slate-100 px-3 py-2">
                <p className="mb-1 inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-slate-700">{t("about.usage")}</p>
                <p>{t("about.usageText")}</p>
                <a
                  href="https://github.com/iambupu/mod_watcher_agent/blob/main/README.md"
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex items-center rounded-md border border-sky-200 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 hover:bg-sky-100"
                >
                  {t("about.usageLink")}
                </a>
              </div>
              <div className="rounded-lg border border-slate-100 px-3 py-2">
                <p className="mb-1 inline-flex items-center rounded-full bg-slate-100 px-2 py-0.5 text-[11px] font-semibold tracking-wide text-slate-700">{t("about.developer")}</p>
                <p>{t("about.developerText")}</p>
                <a
                  href="https://github.com/iambupu"
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex items-center rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-slate-100"
                >
                  {t("about.githubProfile")}
                </a>
              </div>
            </div>
        </ModalShell>
      )}
    </aside>
  );
};

export default AppSidebar;
