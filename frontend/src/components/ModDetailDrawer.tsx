import React from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink, Clock } from "lucide-react";
import { useUIStore } from "@/stores/uiStore";
import { Drawer } from "@/components/ui/Drawer";
import { Badge } from "@/components/ui/Badge";
import { SourceBadge } from "@/components/SourceBadge";
import type { ModItem } from "@/types";

interface ModDetailDrawerProps {
  open: boolean;
  onClose: () => void;
  mod?: ModItem | null;
  updateHistory?: Array<{ version: string; date: string; changelog?: string }>;
  userNote?: string;
  externalLinks?: Array<{ label: string; url: string }>;
}

export const ModDetailDrawer: React.FC<ModDetailDrawerProps> = ({
  open,
  onClose,
  mod,
  updateHistory = [],
  userNote,
  externalLinks = [],
}) => {
  const { t } = useTranslation();
  const summaryMode = useUIStore((s) => s.summaryMode);

  if (!mod) return null;

  return (
    <Drawer open={open} onClose={onClose} title={t("mod.detail")}>
      <div className="space-y-4">
        {mod.thumbnail_url && (
          <img src={mod.thumbnail_url} alt={mod.title} className="w-full rounded-lg object-cover" />
        )}

        <div>
          <div className="flex items-center gap-2 mb-1">
            <SourceBadge source={mod.source} />
            {mod.category && <Badge variant="info">{mod.category}</Badge>}
          </div>
          <h2 className="text-xl font-bold text-gray-900">{mod.title}</h2>
          <div className="flex items-center gap-3 mt-1 text-sm text-gray-500">
            {mod.author && <span>{mod.author}</span>}
            {mod.game && <span>{mod.game}</span>}
            {mod.version && <span>v{mod.version}</span>}
          </div>
        </div>

        <div className="flex items-center gap-4 text-sm text-gray-500">
          {mod.downloads !== undefined && (
            <span>{mod.downloads.toLocaleString()} {t("mod.downloads")}</span>
          )}
          {mod.endorsements !== undefined && (
            <span>{mod.endorsements.toLocaleString()} {t("mod.endorsements")}</span>
          )}
          {mod.likes !== undefined && (
            <span>{mod.likes.toLocaleString()} {t("mod.likes")}</span>
          )}
        </div>

        {summaryMode === "translated" ? (
          mod.translated_summary ? (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-1">{t("mod.translatedSummary")}</h3>
              <p className="text-sm text-gray-600 whitespace-pre-wrap">{mod.translated_summary}</p>
            </div>
          ) : mod.original_summary ? (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-1">{t("mod.originalSummary")}</h3>
              <p className="text-sm text-gray-600 whitespace-pre-wrap">{mod.original_summary}</p>
            </div>
          ) : null
        ) : summaryMode === "bilingual" ? (
          <div className="space-y-2">
            {mod.original_summary && (
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-1">{t("mod.originalSummary")}</h3>
                <p className="text-sm text-gray-600 whitespace-pre-wrap">{mod.original_summary}</p>
              </div>
            )}
            {mod.translated_summary && mod.translated_summary !== mod.original_summary && (
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-1">{t("mod.translatedSummary")}</h3>
                <p className="text-sm text-gray-600 whitespace-pre-wrap">{mod.translated_summary}</p>
              </div>
            )}
          </div>
        ) : (
          mod.original_summary && (
            <div>
              <h3 className="text-sm font-medium text-gray-700 mb-1">{t("mod.originalSummary")}</h3>
              <p className="text-sm text-gray-600 whitespace-pre-wrap">{mod.original_summary}</p>
            </div>
          )
        )}

        {(() => {
          try {
            const tags: string[] = JSON.parse(mod.tags_json || "[]");
            return tags.length > 0 ? (
              <div>
                <h3 className="text-sm font-medium text-gray-700 mb-1">{t("mod.tags")}</h3>
                <div className="flex flex-wrap gap-1">
                  {tags.map((tag: string) => (
                    <Badge key={tag}>{tag}</Badge>
                  ))}
                </div>
              </div>
            ) : null;
          } catch {
            return null;
          }
        })()}

        {updateHistory.length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-2">{t("updates.title")}</h3>
            <div className="space-y-2">
              {updateHistory.map((update, idx) => (
                <div key={idx} className="border-l-2 border-blue-200 pl-3">
                  <div className="flex items-center gap-2 text-sm">
                    <span className="font-medium">v{update.version}</span>
                    <Clock size={12} className="text-gray-400" />
                    <span className="text-gray-500">{new Date(update.date).toLocaleDateString()}</span>
                  </div>
                  {update.changelog && (
                    <p className="text-xs text-gray-500 mt-1">{update.changelog}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {userNote && (
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-1">{t("favorites.notes")}</h3>
            <p className="text-sm text-gray-600">{userNote}</p>
          </div>
        )}

        {externalLinks.length > 0 && (
          <div>
            <h3 className="text-sm font-medium text-gray-700 mb-1">{t("mod.openOriginal")}</h3>
            <div className="space-y-1">
              {externalLinks.map((link, idx) => (
                <a
                  key={idx}
                  href={link.url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center gap-1 text-sm text-blue-600 hover:underline"
                >
                  <ExternalLink size={14} />
                  {link.label}
                </a>
              ))}
            </div>
          </div>
        )}
      </div>
    </Drawer>
  );
};
