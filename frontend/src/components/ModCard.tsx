import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Download, ThumbsUp, Clock, ExternalLink, Heart, EyeOff, Gamepad2, Languages, Sparkles, ChevronDown, ChevronUp, X } from "lucide-react";
import { SourceBadge } from "@/components/SourceBadge";
import { Button } from "@/components/ui/Button";
import { useUIStore } from "@/stores/uiStore";
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

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen).trimEnd() + "...";
}

function formatDate(dateStr?: string): string {
  if (!dateStr) return "";
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
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

  const hasOriginal = !!mod.original_summary;
  const hasTranslated = !!mod.translated_summary;
  const originalSummary = hasOriginal ? truncate(mod.original_summary!, 200) : "";
  const translatedSummary = hasTranslated ? truncate(mod.translated_summary!, 200) : "";
  const gameLabel = mod.game || mod.game_domain || "";

  let summary: string;
  if (summaryMode === "translated") {
    summary = translatedSummary;
  } else if (summaryMode === "bilingual") {
    if (hasOriginal && hasTranslated) {
      summary = `${translatedSummary}\n——\n${originalSummary}`;
    } else if (hasOriginal) {
      summary = originalSummary;
    } else {
      summary = t("mod.noSummary");
    }
  } else {
    summary = originalSummary || t("mod.noSummary");
  }
  const fullSummary = summaryMode === "bilingual" && hasOriginal && hasTranslated
    ? `${mod.translated_summary}\n——\n${mod.original_summary}`
    : summaryMode === "translated"
      ? mod.translated_summary || ""
      : mod.original_summary || "";
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
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm hover:shadow-md transition-shadow flex flex-col overflow-hidden">
      <div className="relative aspect-[300/169] bg-gradient-to-br from-gray-100 to-gray-200 flex-shrink-0">
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
        <div className="absolute top-2 left-2">
          <div className="flex max-w-[calc(100%-3rem)] flex-wrap gap-1.5">
            <SourceBadge source={mod.source} />
            {mod.adult_content === true && (
              <span
                className="inline-flex items-center rounded-md border border-red-200 bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 shadow-sm"
                title="Adult content"
              >
                R18
              </span>
            )}
            {gameLabel && (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white/90 px-2 py-0.5 text-xs font-medium text-gray-700 shadow-sm backdrop-blur-sm"
                title={gameLabel}
              >
                <Gamepad2 size={12} />
                <span className="max-w-40 truncate">{gameLabel}</span>
              </span>
            )}
          </div>
        </div>
        {onToggleFavorite && (
          <button
            onClick={(e) => { e.preventDefault(); onToggleFavorite(); }}
            className="absolute top-2 right-2 p-1.5 rounded-full bg-white/80 backdrop-blur-sm shadow-sm hover:bg-white transition-colors"
            aria-label={isFavorited ? "Remove from favorites" : "Add to favorites"}
          >
            <Heart
              size={16}
              className={isFavorited ? "fill-red-500 text-red-500" : "text-gray-400 hover:text-red-400"}
            />
          </button>
        )}
        {onIgnore && (
          <button
            onClick={(e) => { e.preventDefault(); onIgnore(); }}
            className="absolute top-2 right-10 p-1.5 rounded-full bg-white/80 backdrop-blur-sm shadow-sm hover:bg-white transition-colors"
            aria-label="Ignore this mod"
          >
            <EyeOff size={16} className="text-gray-400 hover:text-red-500" />
          </button>
        )}
      </div>

      <div className="flex flex-col flex-1 p-4 gap-2">
        <a
          href={mod.url}
          target="_blank"
          rel="noopener noreferrer"
          className="text-sm font-semibold text-gray-900 hover:text-blue-600 transition-colors line-clamp-2"
          title={mod.title}
        >
          {mod.title}
        </a>

        <span className="text-xs text-gray-500 truncate">{gameLabel}</span>

        <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
          {mod.downloads !== undefined && mod.downloads !== null && (
            <span className="inline-flex items-center gap-1">
              <Download size={12} />
              {mod.downloads.toLocaleString()}
            </span>
          )}
          {mod.endorsements !== undefined && mod.endorsements !== null && (
            <span className="inline-flex items-center gap-1">
              <ThumbsUp size={12} />
              {mod.endorsements.toLocaleString()}
            </span>
          )}
          {mod.updated_at_remote && (
            <span className="inline-flex items-center gap-1">
              <Clock size={12} />
              {formatDate(mod.updated_at_remote)}
            </span>
          )}
        </div>

        <div className="space-y-2">
          {summary ? (
            <p
              ref={summaryRef}
              onClick={(e) => {
                if (!canToggleSummary) return;
                e.preventDefault();
                setSummaryExpanded((v) => !v);
              }}
              className={`text-sm text-gray-500 leading-relaxed whitespace-pre-line ${summaryExpanded ? "" : summaryMode === "bilingual" ? "line-clamp-4" : "line-clamp-3"} ${canToggleSummary ? "cursor-pointer" : ""}`}
              title={canToggleSummary ? (summaryExpanded ? t("mod.collapseSummary") : t("mod.expandSummary")) : undefined}
            >
              {summaryExpanded ? fullSummary || summary : summary}
            </p>
          ) : (
            <p className="text-sm text-gray-400">{t("mod.noSummary")}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 pt-1">
            {canToggleSummary && (
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); setSummaryExpanded((v) => !v); }}
                className="inline-flex items-center gap-1 rounded-md bg-gray-100 px-2 py-1 text-xs font-medium text-gray-700 transition-colors hover:bg-gray-200 hover:text-gray-900"
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
                className="inline-flex items-center gap-1 rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700 transition-colors hover:bg-blue-100 disabled:opacity-50"
              >
                <Languages size={13} />
                {regeneratingSummary ? t("common.loading") : t("mod.regenerateSummary")}
              </button>
            )}
            {onGenerateIntroduction && (
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); handleOpenIntroduction(); }}
                disabled={generatingIntroduction}
                className="inline-flex items-center gap-1 rounded-md bg-purple-50 px-2 py-1 text-xs font-medium text-purple-700 transition-colors hover:bg-purple-100 disabled:opacity-50"
              >
                <Sparkles size={13} />
                {generatingIntroduction ? "生成介绍中" : mod.ai_introduction || introduction ? "查看 AI 介绍" : "AI 介绍"}
              </button>
            )}
          </div>
        </div>

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {tags.slice(0, 4).map((tag) => (
              <span
                key={tag}
                className="text-xs bg-gray-100 text-gray-600 px-1.5 py-0.5 rounded"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <div className="mt-auto pt-3">
          <a href={mod.url} target="_blank" rel="noopener noreferrer">
            <Button size="sm" variant="outline" className="w-full">
              <ExternalLink size={14} />
              <span className="ml-1.5">{t("common.viewMod")}</span>
            </Button>
          </a>
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
                <h3 className="text-base font-semibold text-gray-900">AI 介绍</h3>
                <p className="text-xs text-gray-500 line-clamp-1">{mod.title}</p>
              </div>
              <button type="button" className="rounded-md p-1 text-gray-500 hover:bg-gray-100" onClick={() => setIntroductionOpen(false)}>
                <X size={18} />
              </button>
            </div>
            <div className="max-h-[62vh] overflow-y-auto px-5 py-4">
              {generatingIntroduction && !introduction ? (
                <p className="text-sm text-gray-500">正在使用 LLM 生成更详细的 Mod 介绍...</p>
              ) : introError ? (
                <p className="text-sm text-red-600">{introError}</p>
              ) : (
                <p className="whitespace-pre-wrap text-sm leading-6 text-gray-700">{introduction || mod.ai_introduction || "暂无 AI 介绍"}</p>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
