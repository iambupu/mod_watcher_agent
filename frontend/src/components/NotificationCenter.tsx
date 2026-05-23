import { useCallback, useState } from "react";
import { useTranslation } from "react-i18next";
import { X, CheckCheck, BellOff, Loader2, AlertCircle } from "lucide-react";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import {
  fetchNotifications,
  markNotificationsRead,
  markAllNotificationsRead,
  fetchUnreadCount,
} from "@/api/notifications";
import { MarkdownText } from "@/components/MarkdownText";
import type { NotificationItem } from "@/types";

interface NotificationCenterProps {
  open: boolean;
  onClose: () => void;
}

export function NotificationCenter({ open, onClose }: NotificationCenterProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const { data, isLoading, isError } = useQuery({
    queryKey: ["notifications"],
    queryFn: () => fetchNotifications(0, 50),
    refetchInterval: open ? 15000 : false,
    enabled: open,
  });

  const { data: unread } = useQuery({
    queryKey: ["notifications-unread-count"],
    queryFn: fetchUnreadCount,
    refetchInterval: 10000,
  });

  const markReadMutation = useMutation({
    mutationFn: markNotificationsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });

  const markAllReadMutation = useMutation({
    mutationFn: markAllNotificationsRead,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["notifications"] });
      queryClient.invalidateQueries({ queryKey: ["notifications-unread-count"] });
    },
  });

  const handleMarkRead = useCallback(
    (id: number) => {
      markReadMutation.mutate([id]);
    },
    [markReadMutation],
  );

  const handleMarkAllRead = useCallback(() => {
    markAllReadMutation.mutate();
  }, [markAllReadMutation]);

  if (!open) return null;

  const items = data?.items ?? [];
  const unreadCount = unread?.count ?? 0;

  const channelLabel = (ch: string) => {
    if (ch === "telegram" || ch === "tg") return "Telegram";
    if (ch === "discord" || ch === "dc") return "Discord";
    if (ch === "desktop") return t("notifications.channelDesktop");
    if (ch === "all") return "Telegram / Discord";
    return ch;
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* backdrop */}
      <div className="absolute inset-0 bg-black/30" onClick={onClose} />
      {/* panel */}
      <div className="relative w-full max-w-md bg-white shadow-xl flex flex-col h-full">
        {/* header */}
        <div className="flex items-center justify-between px-4 py-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold text-gray-900">{t("notifications.title")}</h2>
            {unreadCount > 0 && (
              <span className="inline-flex items-center justify-center rounded-full bg-red-500 px-2 py-0.5 text-xs font-bold text-white">
                {unreadCount > 99 ? "99+" : unreadCount}
              </span>
            )}
          </div>
          <div className="flex items-center gap-1">
            {unreadCount > 0 && (
              <button
                type="button"
                onClick={handleMarkAllRead}
                className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
                title={t("notifications.markAllRead")}
              >
                <CheckCheck size={16} />
              </button>
            )}
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-gray-500 hover:bg-gray-100 hover:text-gray-700"
            >
              <X size={18} />
            </button>
          </div>
        </div>
        {/* list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center h-full text-gray-400">
              <Loader2 className="animate-spin" size={24} />
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-2">
              <AlertCircle size={40} className="text-red-400" />
              <p className="text-sm">{t("notifications.loadError")}</p>
            </div>
          ) : items.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full text-gray-400 gap-2">
              <BellOff size={40} />
              <p className="text-sm">{t("notifications.empty")}</p>
            </div>
          ) : (
            items.map((item) => (
              <NotificationRow
                key={item.id}
                item={item}
                channelLabel={channelLabel}
                onMarkRead={handleMarkRead}
              />
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function NotificationRow({
  item,
  channelLabel,
  onMarkRead,
}: {
  item: NotificationItem;
  channelLabel: (ch: string) => string;
  onMarkRead: (id: number) => void;
}) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const timeStr = item.created_at
    ? new Date(item.created_at).toLocaleString()
    : "";

  const handleClick = () => {
    setExpanded((value) => !value);
    if (!item.read) {
      onMarkRead(item.id);
    }
  };

  return (
    <div
      className={`px-4 py-3 border-b border-gray-100 cursor-pointer transition-colors ${
        item.read ? "bg-white" : "bg-blue-50/70"
      } hover:bg-gray-50`}
      onClick={handleClick}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span
              className={`inline-block w-2 h-2 rounded-full flex-shrink-0 ${
                item.read ? "bg-transparent" : "bg-blue-500"
              }`}
            />
            <p className="text-sm font-medium text-gray-900 truncate">{item.subject}</p>
          </div>
          {expanded ? (
            <MarkdownText text={item.body} className="mt-1 text-xs text-gray-600" />
          ) : (
            <p className="mt-0.5 truncate text-xs leading-5 text-gray-500">
              {item.body}
            </p>
          )}
          <div className="mt-1 flex items-center gap-2 text-xs text-gray-400">
            <span>{timeStr}</span>
            <span>·</span>
            <span>{channelLabel(item.channel)}</span>
            <span>·</span>
            <span
              className={statusClassName(item.status)}
              title={item.error_message || undefined}
            >
              {statusLabel(item.status, t)}
            </span>
          </div>
          {expanded && item.error_message && (
            <p className="mt-1 text-xs leading-5 text-amber-700">{item.error_message}</p>
          )}
        </div>
      </div>
    </div>
  );
}

function statusLabel(status: string, t: (key: string) => string): string {
  if (status === "sent") return t("notifications.sent");
  if (status === "pending") return t("notifications.pending");
  if (status === "skipped") return t("notifications.skipped");
  return t("notifications.failed");
}

function statusClassName(status: string): string {
  if (status === "sent") return "text-green-600";
  if (status === "pending") return "text-blue-600";
  if (status === "skipped") return "text-amber-600";
  return "text-red-500";
}
