import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  CheckCheck,
  Eye,
  EyeOff,
  ExternalLink,
  RefreshCw,
  AlertCircle,
  Inbox,
} from "lucide-react";
import { Card, CardContent, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import AppSidebar from "@/components/layout/AppSidebar";
import { fetchUpdates, markUpdateSeen, markAllUpdatesSeen } from "@/api/updates";
import { useUIStore } from "@/stores/uiStore";
import type { UpdateEvent } from "@/types";

const SkeletonCard: React.FC = () => (
  <div className="mb-6 relative pl-8 border-l-2 border-gray-200">
    <div className="absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 bg-gray-200 border-gray-300" />
    <Card className="animate-pulse">
      <CardHeader className="pb-2">
        <div className="flex justify-between items-start">
          <div className="h-5 bg-gray-200 rounded w-48" />
          <div className="h-4 bg-gray-200 rounded w-10" />
        </div>
        <div className="h-4 bg-gray-100 rounded w-36 mt-2" />
      </CardHeader>
      <CardContent>
        <div className="flex items-center gap-3 mb-3">
          <div className="h-6 bg-gray-200 rounded w-16" />
          <ArrowRight className="h-4 w-4 text-gray-300" />
          <div className="h-6 bg-gray-200 rounded w-16" />
        </div>
        <div className="flex gap-2">
          <div className="h-8 bg-gray-200 rounded w-24" />
          <div className="h-8 bg-gray-200 rounded w-20" />
        </div>
      </CardContent>
    </Card>
  </div>
);

const TimelineCard: React.FC<{
  event: UpdateEvent;
  markingId: number | null;
  onMarkSeen: (id: number) => void;
}> = ({ event, markingId, onMarkSeen }) => {
  const { t } = useTranslation();
  const summaryMode = useUIStore((s) => s.summaryMode);
  return (
  <div className="mb-6 relative">
    <div className="relative pl-8 border-l-2 border-gray-200">
      <div
        className={`absolute -left-[9px] top-1 w-4 h-4 rounded-full border-2 ${
          event.seen ? "bg-gray-200 border-gray-300" : "bg-blue-500 border-blue-400"
        }`}
      />
      <Card className={event.seen ? "opacity-70" : ""}>
        <CardHeader className="pb-2">
          <div className="flex justify-between items-start">
            <h3 className="text-lg font-semibold text-gray-900">
              <a
                href={event.mod.url || "#"}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:underline hover:text-blue-600 transition-colors"
              >
                {event.mod.title || `Mod #${event.modId}`}
              </a>
            </h3>
            {!event.seen && (
              <Badge variant="danger">{t("common.new")}</Badge>
            )}
            {event.seen && (
              <Badge variant="default">{t("common.seen")}</Badge>
            )}
          </div>
          <p className="text-sm text-gray-500 mt-1">
            {new Date(event.detectedAt).toLocaleString()}
          </p>
          {event.mod.game && (
            <p className="text-xs text-gray-400 mt-0.5">{event.mod.game}</p>
          )}
        </CardHeader>
        <CardContent>
          {(event.oldVersion || event.newVersion) && (
            <div className="flex items-center gap-3 mb-3">
              <span className="px-2 py-1 bg-gray-100 rounded text-sm text-gray-500">
                {event.oldVersion || "?"}
              </span>
              <ArrowRight className="h-4 w-4 text-gray-400" />
              <span className="px-2 py-1 bg-blue-50 text-blue-700 rounded text-sm font-medium">
                {event.newVersion || "?"}
              </span>
            </div>
          )}

          {event.changeSummary && (
            <p className="text-sm text-gray-600 mb-3 line-clamp-2">{event.changeSummary}</p>
          )}

          {summaryMode !== 'original' && event.mod.translated_summary && (
            <p className="text-sm text-gray-600 mb-2 italic">{event.mod.translated_summary}</p>
          )}

          <div className="flex gap-2">
            {!event.seen && (
              <Button
                size="sm"
                variant="outline"
                disabled={markingId === event.id}
                onClick={() => onMarkSeen(event.id)}
              >
                {markingId === event.id ? t("updates.marking") : t("updates.markSeen")}
              </Button>
            )}
            {event.mod.url && (
              <a
                href={event.mod.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center justify-center rounded-md font-medium transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 px-2 py-1 text-sm text-gray-600 hover:bg-gray-100 hover:text-gray-900"
              >
                <ExternalLink size={14} className="mr-1" />
                {t("common.viewMod")}
              </a>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  </div>
  );
};

const Updates: React.FC = () => {
  const { t } = useTranslation();
  const [showUnseenOnly, setShowUnseenOnly] = useState(false);
  const [markingId, setMarkingId] = useState<number | null>(null);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["updates"],
    queryFn: () => fetchUpdates({ limit: 100 }),
  });

  const filteredEvents = React.useMemo(() => {
    if (!data?.items) return [];
    return showUnseenOnly ? data.items.filter((e) => !e.seen) : data.items;
  }, [data, showUnseenOnly]);

  async function handleMarkSeen(eventId: number) {
    setMarkingId(eventId);
    try {
      await markUpdateSeen(eventId);
      refetch();
    } catch (e) {
      alert(`Failed to mark as seen: ${(e as Error).message}`);
    } finally {
      setMarkingId(null);
    }
  }

  async function handleMarkAllSeen() {
    try {
      await markAllUpdatesSeen();
      refetch();
    } catch (e) {
      alert(`Failed: ${(e as Error).message}`);
    }
  }

  const unseenCount = data?.items.filter((e) => !e.seen).length ?? 0;

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <AppSidebar active="updates" />

        <main className="flex-1 overflow-y-auto p-6">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
              <h2 className="text-2xl font-bold text-gray-900">{t("updates.title")}</h2>
              {unseenCount > 0 && (
                <Badge variant="danger">{t("common.new_count", { count: unseenCount })}</Badge>
              )}
            </div>
            <div className="flex items-center gap-2">
              <Button
                size="sm"
                variant={showUnseenOnly ? "default" : "outline"}
                onClick={() => setShowUnseenOnly(!showUnseenOnly)}
              >
                {showUnseenOnly ? (
                  <Eye size={14} className="mr-1" />
                ) : (
                  <EyeOff size={14} className="mr-1" />
                )}
                {showUnseenOnly ? t("updates.showAll") : t("updates.unseenOnly")}
              </Button>
              {unseenCount > 0 && (
                <Button size="sm" variant="outline" onClick={handleMarkAllSeen}>
                  <CheckCheck size={14} className="mr-1" />
                  {t("updates.markAllSeen")}
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={() => refetch()}>
                <RefreshCw size={14} className="mr-1" />
                {t("common.refresh")}
              </Button>
            </div>
          </div>

          {isLoading && (
            <div className="max-w-2xl mx-auto">
              <SkeletonCard />
              <SkeletonCard />
              <SkeletonCard />
            </div>
          )}

          {isError && (
            <div className="max-w-2xl mx-auto">
              <Card className="border-red-200 bg-red-50">
                <CardContent className="py-8 text-center">
                  <AlertCircle size={48} className="mx-auto text-red-400 mb-4" />
                  <h3 className="text-lg font-semibold text-red-800 mb-2">{t("updates.loadFailed")}</h3>
                  <p className="text-sm text-red-600 mb-4">{(error as Error).message}</p>
                  <Button variant="destructive" size="sm" onClick={() => refetch()}>
                    <RefreshCw size={14} className="mr-1" />
                    {t("common.retry")}
                  </Button>
                </CardContent>
              </Card>
            </div>
          )}

          {!isLoading && !isError && filteredEvents.length === 0 && (
            <div className="max-w-2xl mx-auto">
              <Card>
                <CardContent className="py-12 text-center">
                  <Inbox size={48} className="mx-auto text-gray-300 mb-4" />
                  <h3 className="text-lg font-semibold text-gray-700 mb-2">{t("updates.noUpdates")}</h3>
                  <p className="text-sm text-gray-500">
                    {t("updates.emptyDesc")}
                  </p>
                </CardContent>
              </Card>
            </div>
          )}

          {!isLoading && !isError && filteredEvents.length > 0 && (
            <div className="max-w-2xl mx-auto">
              {filteredEvents.map((event) => (
                <TimelineCard
                  key={event.id}
                  event={event}
                  markingId={markingId}
                  onMarkSeen={handleMarkSeen}
                />
              ))}
            </div>
          )}
        </main>
      </div>
    </div>
  );
};

export default Updates;
