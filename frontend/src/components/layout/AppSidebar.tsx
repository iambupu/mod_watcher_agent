import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import {
  Bell,
  FileText,
  Heart,
  LayoutDashboard,
  MessageCircle,
  Search,
  Settings,
  SlidersHorizontal,
  PanelLeftClose,
  PanelLeftOpen,
  Info,
  X,
} from "lucide-react";
import { useUIStore } from "@/stores/uiStore";

type NavKey = "agent" | "dashboard" | "discover" | "favorites" | "updates" | "rules" | "logs" | "settings";

interface AppSidebarProps {
  active: NavKey;
}

const NAV_ITEMS: Array<{ key: NavKey; href: string; icon: React.ReactNode; labelKey: string }> = [
  { key: "agent", href: "/agent", icon: <MessageCircle size={18} />, labelKey: "nav.agent" },
  { key: "dashboard", href: "/", icon: <LayoutDashboard size={18} />, labelKey: "nav.dashboard" },
  { key: "discover", href: "/discover", icon: <Search size={18} />, labelKey: "nav.discover" },
  { key: "favorites", href: "/favorites", icon: <Heart size={18} />, labelKey: "nav.favorites" },
  { key: "updates", href: "/updates", icon: <Bell size={18} />, labelKey: "nav.updates" },
  { key: "rules", href: "/rules", icon: <SlidersHorizontal size={18} />, labelKey: "nav.rules" },
  { key: "logs", href: "/logs", icon: <FileText size={18} />, labelKey: "nav.logs" },
  { key: "settings", href: "/settings", icon: <Settings size={18} />, labelKey: "nav.settings" },
];

const AppSidebar: React.FC<AppSidebarProps> = ({ active }) => {
  const { t } = useTranslation();
  const sidebarOpen = useUIStore((s) => s.sidebarOpen);
  const toggleSidebar = useUIStore((s) => s.toggleSidebar);
  const [aboutOpen, setAboutOpen] = useState(false);
  const appVersion = import.meta.env.VITE_APP_VERSION || "0.1.1";

  return (
    <aside className={`${sidebarOpen ? "w-64" : "w-20"} bg-white border-r border-gray-200 flex flex-col transition-all duration-150`}>
      <div className={`px-4 py-4 border-b border-gray-200 flex items-center ${sidebarOpen ? "gap-2" : "justify-center"}`}>
        <img src="/mwlogo.png" alt="Mod Watcher" className="h-10 w-auto" />
        {sidebarOpen && <span className="text-lg font-bold text-gray-900">{t("nav.brand")}</span>}
        <button
          type="button"
          onClick={toggleSidebar}
          className={`rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-900 ${sidebarOpen ? "ml-auto" : ""}`}
          title={sidebarOpen ? t("settings.hideSidebar") : t("settings.showSidebar")}
          aria-label={sidebarOpen ? t("settings.hideSidebar") : t("settings.showSidebar")}
        >
          {sidebarOpen ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}
        </button>
      </div>

      <nav className={`flex-1 py-4 space-y-1 ${sidebarOpen ? "px-3" : "px-2"}`}>
        {NAV_ITEMS.map((item) => {
          const isActive = item.key === active;
          return (
            <a
              key={item.key}
              href={item.href}
              title={t(item.labelKey)}
              className={`flex items-center rounded-lg text-sm font-medium transition-colors ${
                sidebarOpen ? "gap-3 px-4 py-2.5" : "justify-center px-2 py-2.5"
              } ${
                isActive
                  ? "bg-blue-50 text-blue-700"
                  : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              }`}
            >
              {item.icon}
              {sidebarOpen && t(item.labelKey)}
            </a>
          );
        })}
      </nav>
      <div className={`border-t border-gray-200 py-3 ${sidebarOpen ? "px-3" : "px-2"}`}>
        <button
          type="button"
          onClick={() => setAboutOpen(true)}
          className={`w-full flex items-center rounded-lg text-sm font-medium text-gray-600 hover:bg-gray-100 hover:text-gray-900 ${
            sidebarOpen ? "gap-2 px-3 py-2" : "justify-center px-2 py-2"
          }`}
          title={t("about.title")}
        >
          <Info size={16} />
          {sidebarOpen && <span>{t("about.title")}</span>}
        </button>
      </div>
      {aboutOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 px-4">
          <div className="w-full max-w-md rounded-xl bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-4 py-3">
              <h3 className="text-base font-semibold text-gray-900">Mod Watcher（模组巡望者）</h3>
              <button
                type="button"
                onClick={() => setAboutOpen(false)}
                className="rounded-md p-1 text-gray-500 hover:bg-gray-100 hover:text-gray-800"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-4 px-4 py-4 text-sm text-gray-700">
              <div className="flex justify-center pb-1">
                <img src="/mwlogo.png" alt="Mod Watcher" className="h-40 w-auto" />
              </div>
              <div className="rounded-lg border border-gray-100 bg-gray-50 px-3 py-2">
                <p className="text-xs text-gray-500">{t("about.version")}</p>
                <p className="font-medium">v{appVersion}</p>
              </div>
              <div className="rounded-lg border border-gray-100 px-3 py-2">
                <p className="text-xs text-gray-500">{t("about.changelog")}</p>
                <p>{t("about.changelogText")}</p>
              </div>
              <div className="rounded-lg border border-gray-100 px-3 py-2">
                <p className="text-xs text-gray-500">{t("about.usage")}</p>
                <p>{t("about.usageText")}</p>
                <a
                  href="https://github.com/iambupu/mod_watcher_agent/blob/main/README.md"
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex items-center rounded-md border border-blue-200 bg-blue-50 px-2.5 py-1 text-xs font-medium text-blue-700 hover:bg-blue-100"
                >
                  {t("about.usageLink")}
                </a>
              </div>
              <div className="rounded-lg border border-gray-100 px-3 py-2">
                <p className="text-xs text-gray-500">{t("about.developer")}</p>
                <p>{t("about.developerText")}</p>
                <a
                  href="https://github.com/iambupu"
                  target="_blank"
                  rel="noreferrer"
                  className="mt-2 inline-flex items-center rounded-md border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100"
                >
                  {t("about.githubProfile")}
                </a>
              </div>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
};

export default AppSidebar;
