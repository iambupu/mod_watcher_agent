// 中文注释：提供规则编辑器里的 NotificationSection 表单组件。

import React from "react";
import { useTranslation } from "react-i18next";
import { Switch } from "@/components/ui/Switch";
import { useRuleEditorStore } from "@/stores/ruleEditorStore";
import type { NotifyMode } from "@/types";

const NOTIFY_MODES: NotifyMode[] = ["instant", "daily_digest", "weekly_digest"];
const CHANNELS = ["desktop", "telegram", "discord"] as const;

export const NotificationSection: React.FC = () => {
  const { t } = useTranslation();
  const notification = useRuleEditorStore((s) => s.draft.notification);
  const updateNotification = useRuleEditorStore((s) => s.updateNotification);

  const modeLabelKey: Record<NotifyMode, string> = {
    instant: "rules.notification.modeInstant",
    daily_digest: "rules.notification.modeDaily",
    weekly_digest: "rules.notification.modeWeekly",
  };
  const channelLabelKey: Record<(typeof CHANNELS)[number], string> = {
    desktop: "rules.notification.channelDesktop",
    telegram: "rules.notification.channelTelegram",
    discord: "rules.notification.channelDiscord",
  };

  const toggleChannel = (channel: string) => {
    const current = notification.channels || [];
    const next = current.includes(channel)
      ? current.filter((c) => c !== channel)
      : [...current, channel];
    updateNotification({ channels: next });
  };

  return (
    <div className="flex flex-col gap-3">
      <Switch
        checked={notification.enabled}
        onCheckedChange={(checked) => updateNotification({ enabled: checked })}
        label={t("rules.notification.enabled")}
      />

      {notification.enabled && (
        <>
          <div className="flex flex-col gap-1">
            <label
              htmlFor="notify-mode-select"
              className="text-sm font-medium text-gray-700"
            >
              {t("rules.notification.mode")}
            </label>
            <select
              id="notify-mode-select"
              value={notification.mode}
              onChange={(e) =>
                updateNotification({ mode: e.target.value as NotifyMode })
              }
              className="w-full rounded-md border border-gray-300 bg-white px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            >
              {NOTIFY_MODES.map((m) => (
                <option key={m} value={m}>
                  {t(modeLabelKey[m])}
                </option>
              ))}
            </select>
          </div>

          <fieldset className="flex flex-col gap-1">
            <legend className="text-sm font-medium text-gray-700">
              {t("rules.notification.channels")}
            </legend>
            <div className="flex flex-col gap-1">
              {CHANNELS.map((ch) => (
                <label
                  key={ch}
                  className="flex items-center gap-2 text-sm text-gray-600 cursor-pointer"
                >
                  <input
                    type="checkbox"
                    checked={(notification.channels || []).includes(ch)}
                    onChange={() => toggleChannel(ch)}
                    className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  {t(channelLabelKey[ch])}
                </label>
              ))}
            </div>
          </fieldset>
        </>
      )}
    </div>
  );
};
