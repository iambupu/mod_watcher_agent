import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { ExternalLink, Heart, EyeOff, Languages, Sparkles, ChevronDown, ChevronUp, X } from "lucide-react";
import { ModStatsLine } from "@/components/ModStatsLine";
import { SourceBadge } from "@/components/SourceBadge";
import { Button } from "@/components/ui/Button";
import { useUIStore } from "@/stores/uiStore";
import { formatModSummary } from "@/utils/modSummary";
import type { ModItem } from "@/types";

interface ModCardProps {
  mod: ModItem;
  isFavorited?: boolean;
  onToggleFavorite?: () => void;
  onIgnore?: () => void;
  onRegenerateSummary?: () => void;
  regeneratingSummary?: boolean;
  onGenerateIntroduction?: () => Promise<string | undefined>;
  generatingIntroduction?: boolean;
  footerContent?: React.ReactNode;
}

function parseTags(tagsJson: string): string[] {
  try {
    return JSON.parse(tagsJson);
  } catch {
    return [];
  }
}

export const ModCard: React.FC<ModCardProps> = ({ mod, isFavorited = false, onToggleFavorite, onIgnore, onRegenerateSummary, regeneratingSummary = false, onGenerateIntroduction, generatingIntroduction = false, footerContent }) => {
  const { t } = useTranslation();
  const summaryMode = useUIStore((s) => s.summaryMode);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [summaryOverflow, setSummaryOverflow] = useState(false);
  const [introductionOpen, setIntroductionOpen] = useState(false);
  const [introduction, setIntroduction] = useState(mod.ai_introduction || "");
  const [introError, setIntroError] = useState("");
  const summaryRef = useRef<HTMLParagraphElement | null>(null);
  const tags = parseTags(mod.tags_json || "[]");

  const gameLabel = mod.game || mod.game_domain || "";
  const summary = formatModSummary({
    original: mod.original_summary,
    translated: mod.translated_summary,
    mode: summaryMode,
    maxLength: 200,
    emptyText: t("mod.noSummary"),
  });
  const fullSummary = formatModSummary({
    original: mod.original_summary,
    translated: mod.translated_summary,
    mode: summaryMode,
  });
  useEffect(() => {
    const el = summaryRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const updateOverflow = () => {
      setSummaryOverflow(el.scrollHeight > el.clientHeight + 1);
    };
    updateOverflow();
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [summary, fullSummary, summaryMode, summaryExpanded]);

  const canToggleSummary = summaryExpanded || summaryOverflow;

  const handleOpenIntroduction = async () => {
    setIntroductionOpen(true);
    setIntroError("");
    if (introduction || mod.ai_introduction) {
      setIntroduction(introduction || mod.ai_introduction || "");
      return;
    }
    if (!onGenerateIntroduction) return;
    try {
      const content = await onGenerateIntroduction();
      setIntroduction(content || "");
    } catch (error) {
      setIntroError(error instanceof Error ? error.message : "Failed to generate introduction");
    }
  };

  return (
    <div className="flex overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm transition hover:-translate-y-0.5 hover:shadow-md flex-col">
      <div
        className={`relative flex-shrink-0 bg-gradient-to-br from-slate-100 to-slate-200 ${
          mod.thumbnail_url ? "aspect-[300/169]" : "aspect-[300/85]"
        }`}
      >
        {mod.thumbnail_url ? (
          <img
            src={mod.thumbnail_url}
            alt={mod.title}
            className="w-full h-full object-cover"
            loading="lazy"
          />
        ) : (
          <div className="w-full h-full flex items-center justify-center text-gray-400">
            <svg className="w-12 h-12" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 16l4.586-4.586a2 2 0 012.828 0L16 16m-2-2l1.586-1.586a2 2 0 012.828 0L20 14m-6-6h.01M6 20h12a2 2 0 002-2V6a2 2 0 00-2-2H6a2 2 0 00-2 2v12a2 2 0 002 2z" />
            </svg>
          </div>
        )}
        <div className="absolute left-3 top-3">
          <div className="flex max-w-[calc(100%-3rem)] flex-wrap gap-2">
            <SourceBadge source={mod.source} className="bg-white/95 shadow-sm backdrop-blur-sm" />
            {mod.adult_content === true && (
              <span
                className="inline-flex items-center rounded-md border border-red-200 bg-red-50/95 px-2 py-0.5 text-xs font-semibold text-red-700 shadow-sm backdrop-blur-sm"
                title="Adult content"
              >
                NSFW
              </span>
            )}
            {gameLabel && (
              <span
                className="inline-flex items-center rounded-md border border-slate-200 bg-white/95 px-2 py-0.5 text-xs font-semibold text-slate-600 shadow-sm backdrop-blur-sm"
                title={gameLabel}
              >
                <span className="max-w-40 truncate">{gameLabel}</span>
              </span>
            )}
          </div>
        </div>
        {onToggleFavorite && (
          <button
            onClick={(e) => { e.preventDefault(); onToggleFavorite(); }}
            className="absolute right-3 top-3 rounded-full bg-white/90 p-2 text-slate-400 shadow-sm backdrop-blur-sm transition hover:bg-white hover:text-red-500"
            aria-label={isFavorited ? t("mod.unfavorite") : t("mod.favorite")}
          >
            <Heart
              size={18}
              className={isFavorited ? "fill-red-500 text-red-500" : ""}
            />
          </button>
        )}
      </div>

      <div className="flex flex-1 flex-col gap-2.5 p-4">
        <a
          href={mod.url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 text-base font-bold leading-snug text-slate-950 transition-colors hover:text-blue-600"
          title={mod.title}
        >
          {mod.title}
        </a>

        <ModStatsLine
          downloads={mod.downloads}
          endorsements={mod.endorsements}
          updatedAt={mod.updated_at_remote}
          className="font-semibold text-slate-400"
        />

        <div className="space-y-2">
          {summary ? (
            <p
              ref={summaryRef}
              onClick={(e) => {
                if (!canToggleSummary) return;
                e.preventDefault();
                setSummaryExpanded((v) => !v);
              }}
              className={`whitespace-pre-line text-sm font-medium leading-6 text-slate-500 ${summaryExpanded ? "" : summaryMode === "bilingual" ? "line-clamp-4" : "line-clamp-3"} ${canToggleSummary ? "cursor-pointer" : ""}`}
              title={canToggleSummary ? (summaryExpanded ? t("mod.collapseSummary") : t("mod.expandSummary")) : undefined}
            >
              {summaryExpanded ? fullSummary || summary : summary}
            </p>
          ) : (
            <p className="text-sm text-slate-400">{t("mod.noSummary")}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {canToggleSummary && (
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); setSummaryExpanded((v) => !v); }}
                className="inline-flex items-center gap-1 rounded-md bg-slate-100 px-2 py-1 text-xs font-semibold text-slate-700 transition-colors hover:bg-slate-200 hover:text-slate-900"
              >
                {summaryExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                {summaryExpanded ? t("mod.collapseSummary") : t("mod.expandSummary")}
              </button>
            )}
            {summaryMode !== "original" && onRegenerateSummary && (
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); onRegenerateSummary(); }}
                disabled={regeneratingSummary}
                className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-1 text-xs font-semibold text-blue-700 transition-colors hover:bg-blue-100 disabled:opacity-50"
              >
                <Languages size={13} />
                {regeneratingSummary ? t("common.loading") : t("mod.regenerateSummary")}
              </button>
            )}
          </div>
        </div>

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.slice(0, 4).map((tag) => (
              <span
                key={tag}
                className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-slate-100 pt-3">
          <a href={mod.url} target="_blank" rel="noopener noreferrer">
            <Button size="sm" variant="ghost" className="bg-blue-50 text-blue-700 hover:bg-blue-100">
              <ExternalLink size={14} />
              <span className="ml-1.5">{t("common.viewMod")}</span>
            </Button>
          </a>
          {onToggleFavorite && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="bg-slate-50 text-slate-700 hover:bg-slate-100"
              onClick={onToggleFavorite}
            >
              <Heart size={14} className={isFavorited ? "fill-red-500 text-red-500" : ""} />
              <span className="ml-1.5">{t(isFavorited ? "mod.unfavorite" : "mod.favorite")}</span>
            </Button>
          )}
          {onIgnore && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="bg-slate-50 text-slate-700 hover:bg-slate-100"
              onClick={onIgnore}
            >
              <EyeOff size={14} />
              <span className="ml-1.5">{t("mod.ignore")}</span>
            </Button>
          )}
          {onGenerateIntroduction && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="bg-purple-50 text-purple-700 hover:bg-purple-100"
              onClick={handleOpenIntroduction}
              disabled={generatingIntroduction}
            >
              <Sparkles size={14} />
              <span className="ml-1.5">{generatingIntroduction ? t("mod.generatingIntroduction") : t("mod.aiIntroduction")}</span>
            </Button>
          )}
        </div>

        {footerContent && (
          <div className="border-t border-gray-100 pt-3">
            {footerContent}
          </div>
        )}
      </div>
      {introductionOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/35 px-4">
          <div className="max-h-[80vh] w-full max-w-2xl overflow-hidden rounded-lg bg-white shadow-xl">
            <div className="flex items-center justify-between border-b border-gray-200 px-5 py-3">
              <div>
                <h3 className="text-base font-semibold text-gray-900">{t("mod.aiIntroduction")}</h3>
                <p className="text-xs text-gray-500 line-clamp-1">{mod.title}</p>
              </div>
              <button type="button" className="rounded-md p-1 text-gray-500 hover:bg-gray-100" onClick={() => setIntroductionOpen(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="max-h-[62vh] overflow-y-auto px-5 py-4">
              {generatingIntroduction && !introduction ? (
                <p className="text-sm text-gray-500">{t("mod.aiIntroductionLoading")}</p>
              ) : introError ? (
                <p className="text-sm text-red-600">{introError}</p>
              ) : (
                <p className="whitespace-pre-wrap text-sm leading-6 text-gray-700">{introduction || mod.ai_introduction || t("mod.noAiIntroduction")}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
