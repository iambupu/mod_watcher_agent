// 中文注释：提供 ModCard 业务组件。

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  EyeOff,
  Heart,
  Languages,
  Sparkles,
} from "lucide-react";
import { ModCardMedia } from "@/components/modCard/ModCardMedia";
import { ModIntroductionModal } from "@/components/modCard/ModIntroductionModal";
import { ModStatsLine } from "@/components/ModStatsLine";
import { Button } from "@/components/ui/Button";
import { useUIStore } from "@/stores/uiStore";
import { Panel } from "@/components/ui/Panel";
import { parseJsonStringArray } from "@/utils/json";
import { formatModSummary } from "@/utils/modSummary";
import { formatModTitle } from "@/utils/modTitle";
import type { ModItem } from "@/types";

interface ModCardProps {
  mod: ModItem;
  isFavorited?: boolean;
  onToggleFavorite?: () => void;
  showBottomFavoriteAction?: boolean;
  onIgnore?: () => void;
  onRegenerateSummary?: () => void;
  regeneratingSummary?: boolean;
  onGenerateIntroduction?: () => Promise<string | undefined>;
  generatingIntroduction?: boolean;
  footerContent?: React.ReactNode;
}

export const ModCard: React.FC<ModCardProps> = ({ mod, isFavorited = false, onToggleFavorite, showBottomFavoriteAction = true, onIgnore, onRegenerateSummary, regeneratingSummary = false, onGenerateIntroduction, generatingIntroduction = false, footerContent }) => {
  const { t } = useTranslation();
  const summaryMode = useUIStore((s) => s.summaryMode);
  const [summaryExpanded, setSummaryExpanded] = useState(false);
  const [summaryOverflow, setSummaryOverflow] = useState(false);
  const [introductionOpen, setIntroductionOpen] = useState(false);
  const [introduction, setIntroduction] = useState(mod.ai_introduction || "");
  const [introError, setIntroError] = useState("");
  const summaryRef = useRef<HTMLParagraphElement | null>(null);
  const tags = parseJsonStringArray(mod.tags_json);
  const displayTitle = formatModTitle(mod, summaryMode);

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
  const summaryIsTruncated = Boolean(fullSummary) && summary !== fullSummary;
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

  const canToggleSummary = summaryExpanded || summaryOverflow || summaryIsTruncated;

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
    <Panel
      as="div"
      padding="none"
      className="group relative flex min-h-full overflow-hidden flex-col border-slate-200/80 bg-[#f8fbff] shadow-[0_12px_30px_rgba(15,23,42,0.07)] transition duration-200 hover:-translate-y-0.5 hover:border-sky-300/70 hover:shadow-[0_18px_42px_rgba(15,23,42,0.11)]"
    >
      <div className="absolute inset-x-0 top-0 z-20 h-px bg-sky-500/60" />
      <ModCardMedia mod={mod} displayTitle={displayTitle} gameLabel={gameLabel} isFavorited={isFavorited} onToggleFavorite={onToggleFavorite} />

      <div className="flex flex-1 flex-col gap-3 p-4">
        <a
          href={mod.url}
          target="_blank"
          rel="noopener noreferrer"
          className="line-clamp-2 whitespace-pre-line text-[15px] font-bold leading-snug text-slate-950 transition-colors hover:text-sky-700"
          title={displayTitle}
        >
          {displayTitle}
        </a>

        <ModStatsLine
          downloads={mod.downloads}
          endorsements={mod.endorsements}
          updatedAt={mod.updated_at_remote}
          className="font-semibold text-slate-500"
        />

        <div className="rounded-lg border border-slate-200/70 bg-white/72 p-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.70)]">
          {summary ? (
            <p
              ref={summaryRef}
              onClick={(e) => {
                if (!canToggleSummary) return;
                e.preventDefault();
                setSummaryExpanded((v) => !v);
              }}
              className={`whitespace-pre-line text-sm font-medium leading-6 text-slate-600 ${summaryExpanded ? "" : summaryMode === "bilingual" ? "line-clamp-4" : "line-clamp-3"} ${canToggleSummary ? "cursor-pointer" : ""}`}
              title={canToggleSummary ? (summaryExpanded ? t("mod.collapseSummary") : t("mod.expandSummary")) : undefined}
            >
              {summaryExpanded ? fullSummary || summary : summary}
            </p>
          ) : (
            <p className="text-sm text-slate-400">{t("mod.noSummary")}</p>
          )}
          <div className="flex flex-wrap items-center gap-2 pt-2">
            {canToggleSummary && (
              <button
                type="button"
                onClick={(e) => { e.preventDefault(); setSummaryExpanded((v) => !v); }}
                className="inline-flex items-center gap-1 rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-xs font-semibold text-slate-700 transition-colors hover:border-sky-200 hover:bg-sky-50 hover:text-sky-800"
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
                className="inline-flex items-center gap-1 rounded-md border border-cyan-200 bg-cyan-50 px-2 py-1 text-xs font-semibold text-cyan-800 transition-colors hover:bg-cyan-100 disabled:opacity-50"
              >
                <Languages size={13} />
                {regeneratingSummary ? t("common.loading") : t("mod.regenerateSummary")}
              </button>
            )}
          </div>
        </div>

        {tags.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {tags.slice(0, 5).map((tag) => (
              <span
                key={tag}
                className="rounded-md border border-slate-200 bg-white/80 px-1.5 py-0.5 text-[11px] font-semibold text-slate-600"
              >
                {tag}
              </span>
            ))}
          </div>
        )}

        <div className="mt-auto flex flex-wrap items-center gap-2 border-t border-slate-200/70 pt-3">
          <a href={mod.url} target="_blank" rel="noopener noreferrer">
            <Button size="sm" variant="ghost" className="border border-sky-200 bg-sky-50 text-sky-800 hover:bg-sky-100">
              <ExternalLink size={14} />
              <span className="ml-1.5">{t("common.viewMod")}</span>
            </Button>
          </a>
          {onToggleFavorite && showBottomFavoriteAction && (
            <Button
              type="button"
              size="sm"
              variant="ghost"
              className="border border-slate-200 bg-white/75 text-slate-700 hover:bg-slate-100"
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
              className="border border-slate-200 bg-white/75 text-slate-700 hover:bg-slate-100"
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
              className="border border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100"
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
      <ModIntroductionModal open={introductionOpen} title={displayTitle} introduction={introduction} fallbackIntroduction={mod.ai_introduction} error={introError} loading={generatingIntroduction} onClose={() => setIntroductionOpen(false)} />
    </Panel>
  );
};
