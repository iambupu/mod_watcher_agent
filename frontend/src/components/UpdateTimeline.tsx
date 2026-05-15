import React from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { UpdateEvent } from "@/types";

interface UpdateTimelineProps {
  updates: UpdateEvent[];
  onMarkSeen?: (id: number) => void;
  onMarkAllSeen?: () => void;
}

export const UpdateTimeline: React.FC<UpdateTimelineProps> = ({ updates, onMarkSeen, onMarkAllSeen }) => {
  const { t } = useTranslation();

  if (updates.length === 0) {
    return <p className="text-sm text-gray-500 py-8 text-center">{t("updates.noUpdates")}</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">{t("updates.title")}</h2>
        {onMarkAllSeen && (
          <Button size="sm" variant="outline" onClick={onMarkAllSeen}>
            {t("updates.markAllSeen")}
          </Button>
        )}
      </div>

      <div className="relative">
        <div className="absolute left-4 top-0 bottom-0 w-0.5 bg-gray-200" />

        <div className="space-y-4">
          {updates.map((update) => (
            <div key={update.id} className="relative pl-10">
              <div
                className={`absolute left-2.5 top-1.5 w-3 h-3 rounded-full border-2 ${
                  update.seen ? "bg-gray-200 border-gray-300" : "bg-blue-500 border-blue-400"
                }`}
              />

              <div className={`border rounded-lg p-3 ${update.seen ? "bg-gray-50" : "bg-blue-50 border-blue-200"}`}>
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-sm">
                      {update.mod.title}
                    </span>
                    {!update.seen && <Badge variant="info">New</Badge>}
                  </div>
                  {!update.seen && onMarkSeen && (
                    <Button size="sm" variant="ghost" onClick={() => onMarkSeen(update.id)}>
                      {t("updates.markSeen")}
                    </Button>
                  )}
                </div>

                {update.oldVersion && update.newVersion && (
                  <div className="mt-1 text-sm text-gray-600">
                    <span className="text-gray-400">{update.oldVersion}</span>
                    {" → "}
                    <span className="font-medium">{update.newVersion}</span>
                  </div>
                )}

                {update.changeSummary && (
                  <p className="mt-1 text-xs text-gray-500">{update.changeSummary}</p>
                )}

                <div className="mt-2 text-xs text-gray-400">
                  {new Date(update.detectedAt).toLocaleString()}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
