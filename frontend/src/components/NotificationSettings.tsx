// 中文注释：提供 NotificationSettings 业务组件。

import React from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/Input";
import { Button } from "@/components/ui/Button";

interface NotificationSettingsProps {
  telegramEnabled: boolean;
  telegramBotToken?: string;
  telegramChatId?: string;
  discordEnabled: boolean;
  discordWebhookUrl?: string;
  notificationsEnabled: boolean;
  systemNotificationsEnabled: boolean;
  onTelegramEnabledChange: (enabled: boolean) => void;
  onTelegramBotTokenChange: (value: string) => void;
  onTelegramChatIdChange: (value: string) => void;
  onDiscordEnabledChange: (enabled: boolean) => void;
  onDiscordWebhookUrlChange: (value: string) => void;
  onNotificationsEnabledChange: (enabled: boolean) => void;
  onSystemNotificationsEnabledChange: (enabled: boolean) => void;
  onTestTelegram?: () => void;
  onTestDiscord?: () => void;
}

export const NotificationSettings: React.FC<NotificationSettingsProps> = ({
  telegramEnabled,
  telegramBotToken = "",
  telegramChatId = "",
  discordEnabled,
  discordWebhookUrl = "",
  notificationsEnabled,
  systemNotificationsEnabled,
  onTelegramEnabledChange,
  onTelegramBotTokenChange,
  onTelegramChatIdChange,
  onDiscordEnabledChange,
  onDiscordWebhookUrlChange,
  onNotificationsEnabledChange,
  onSystemNotificationsEnabledChange,
  onTestTelegram,
  onTestDiscord,
}) => {
  const { t } = useTranslation();

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-base font-semibold text-slate-900">{t("settings.notifications")}</h3>
      </div>

      <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
        <label className="flex cursor-pointer items-center gap-3">
          <input
            type="checkbox"
            checked={notificationsEnabled}
            onChange={(e) => onNotificationsEnabledChange(e.target.checked)}
            className="h-5 w-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
          />
          <div>
            <p className="text-sm font-medium text-gray-700">{t("settings.notificationsToggleLabel")}</p>
            <p className="text-xs text-gray-500">{t("settings.notificationsToggleHint")}</p>
          </div>
        </label>
      </div>

      <div className="rounded-lg border border-slate-200 bg-slate-50/50 p-3">
        <label className="flex cursor-pointer items-center gap-3">
          <input
            type="checkbox"
            checked={systemNotificationsEnabled}
            onChange={(e) => onSystemNotificationsEnabledChange(e.target.checked)}
            disabled={!notificationsEnabled}
            className="h-5 w-5 rounded border-gray-300 text-blue-600 focus:ring-blue-500 disabled:opacity-50"
          />
          <div>
            <p className="text-sm font-medium text-gray-700">{t("settings.systemNotifications")}</p>
            <p className="text-xs text-gray-500">{t("settings.systemNotificationsHint")}</p>
          </div>
        </label>
      </div>

      <div className="space-y-3 rounded-lg border border-slate-200 p-3">
        <label className="flex items-center gap-2 font-medium text-gray-700">
          <input
            type="checkbox"
            checked={telegramEnabled}
            onChange={(e) => onTelegramEnabledChange(e.target.checked)}
            disabled={!notificationsEnabled}
            className="rounded"
          />
          {t("settings.telegramEnabled")}
        </label>

        {telegramEnabled && (
          <>
            <div className="grid gap-3 md:grid-cols-2">
              <Input
                label={t("settings.telegramBotToken")}
                type="password"
                value={telegramBotToken}
                onChange={(e) => onTelegramBotTokenChange(e.target.value)}
                placeholder="123456:ABC-DEF1234ghikl..."
                help={{ titleKey: "settings.help.telegramToken.title", stepsKey: "settings.help.telegramToken.steps", stepCount: 4 }}
              />
              <Input
                label={t("settings.telegramChatId")}
                value={telegramChatId}
                onChange={(e) => onTelegramChatIdChange(e.target.value)}
                placeholder="123456789"
                help={{ titleKey: "settings.help.telegramChatId.title", stepsKey: "settings.help.telegramChatId.steps", stepCount: 5 }}
              />
            </div>
            {onTestTelegram && (
              <Button size="sm" variant="outline" onClick={onTestTelegram}>
                {t("common.test")} Telegram
              </Button>
            )}
          </>
        )}
      </div>

      <div className="space-y-3 rounded-lg border border-slate-200 p-3">
        <label className="flex items-center gap-2 font-medium text-gray-700">
          <input
            type="checkbox"
            checked={discordEnabled}
            onChange={(e) => onDiscordEnabledChange(e.target.checked)}
            disabled={!notificationsEnabled}
            className="rounded"
          />
          {t("settings.discordEnabled")}
        </label>

        {discordEnabled && (
          <>
            <Input
              label={t("settings.discordWebhook")}
              value={discordWebhookUrl}
              onChange={(e) => onDiscordWebhookUrlChange(e.target.value)}
              placeholder="https://discord.com/api/webhooks/..."
              help={{ titleKey: "settings.help.discordWebhook.title", stepsKey: "settings.help.discordWebhook.steps", stepCount: 4 }}
            />
            {onTestDiscord && (
              <Button size="sm" variant="outline" onClick={onTestDiscord}>
                {t("common.test")} Discord
              </Button>
            )}
          </>
        )}
      </div>


    </div>
  );
};
