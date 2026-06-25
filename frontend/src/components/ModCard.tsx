// 中文注释：提供 ModCard 业务组件。

import React, { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  EyeOff,
  Gamepad2,
  Heart,
  ImageIcon,
  Languages,
  ShieldAlert,
  Sparkles,
} from "lucide-react";
import { ModStatsLine } from "@/components/ModStatsLine";
import { SourceBadge } from "@/components/SourceBadge";
import { Button } from "@/components/ui/Button";
import { useUIStore } from "@/stores/uiStore";
import { ModalHeader, ModalShell } from "@/components/ui/Modal";
import { Panel } from "@/components/ui/Panel";
import { parseJsonStringArray } from "@/utils/json";
import { isAdultContent } from "@/utils/modAdult";
import { formatModSummary } from "@/utils/modSummary";
import { formatModTitle } from "@/utils/modTitle";
import type { ModItem } from "@/types";

interface ModCardProps {
  mod: ModItem;
  isFavorited?: boolean;
  onToggleFavorite?: () => void;
  showBottomFavoriteAction?: boolean;
  measureSummaryOverflow?: boolean;
  onIgnore?: () => void;
  onRegenerateSummary?: () => void;
  regeneratingSummary?: boolean;
  onGenerateIntroduction?: () => Promise<string | undefined>;
  generatingIntroduction?: boolean;
  footerContent?: React.ReactNode;
}

const sourceBadgeTone: Record<ModItem["source"], string> = {
  nexusmods:
    "border-cyan-300/70 bg-cyan-50/95 text-cyan-900 shadow-[0_8px_24px_rgba(8,145,178,0.16)]",
  loverslab:
    "border-sky-300/70 bg-sky-50/95 text-sky-900 shadow-[0_8px_24px_rgba(2,132,199,0.16)]",
};

export const ModCard: React.FC<ModCardProps> = ({ mod, isFavorited = false, onToggleFavorite, showBottomFavoriteAction = true, measureSummaryOverflow = true, onIgnore, onRegenerateSummary, regeneratingSummary = false, onGenerateIntroduction, generatingIntroduction = false, footerContent }) => {
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
    if (!measureSummaryOverflow) {
      setSummaryOverflow(false);
      return;
    }
    const el = summaryRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const updateOverflow = () => {
      setSummaryOverflow(el.scrollHeight > el.clientHeight + 1);
    };
    updateOverflow();
    const observer = new ResizeObserver(updateOverflow);
    observer.observe(el);
    return () => observer.disconnect();
  }, [measureSummaryOverflow, summary, fullSummary, summaryMode, summaryExpanded]);

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
      <div
        className={`relative flex-shrink-0 overflow-hidden bg-slate-950 ${
          mod.thumbnail_url ? "aspect-[300/169]" : "aspect-[300/85]"
        }`}
      >
        {mod.thumbnail_url ? (
          <img
            src={mod.thumbnail_url}
            alt={displayTitle}
            className="absolute inset-0 h-full w-full object-cover transition duration-300 group-hover:scale-[1.025]"
            loading="lazy"
            decoding="async"
          />
        ) : (
          <div className="flex h-full w-full items-center justify-center bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.22),transparent_34%),linear-gradient(135deg,#111827,#0f172a)] text-sky-100/55">
            <ImageIcon size={44} strokeWidth={1.35} />
          </div>
        )}
        <div className="absolute inset-0 bg-gradient-to-t from-slate-950/64 via-slate-950/5 to-slate-950/22" />
        <div className="pointer-events-none absolute inset-0 opacity-[0.06] [background-image:linear-gradient(rgba(255,255,255,0.28)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.28)_1px,transparent_1px)] [background-size:22px_22px]" />
        <div className="absolute left-3 top-3">
          <div className="flex max-w-[calc(100%-3rem)] flex-wrap gap-1.5">
            <SourceBadge
              source={mod.source}
              className={`backdrop-blur-md ${sourceBadgeTone[mod.source]}`}
            />
            {isAdultContent(mod.adult_content) && (
              <span
                className="inline-flex items-center gap-1 rounded-md border border-rose-300/70 bg-rose-50/95 px-2 py-0.5 text-xs font-semibold text-rose-800 shadow-[0_8px_24px_rgba(225,29,72,0.14)] backdrop-blur-md"
                title="Adult content"
              >
                <ShieldAlert size={12} strokeWidth={2.2} />
                NSFW
              </span>
            )}
          </div>
        </div>
        {gameLabel && (
          <div className="absolute bottom-3 left-3 right-3">
            <span
              className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-white/15 bg-slate-950/72 px-2.5 py-1 text-xs font-semibold text-sky-50 shadow-[0_10px_26px_rgba(15,23,42,0.32)] backdrop-blur-md"
              title={gameLabel}
            >
              <Gamepad2 size={13} strokeWidth={2.2} />
              <span className="truncate">{gameLabel}</span>
            </span>
          </div>
        )}
        {onToggleFavorite && (
          <button
            onClick={(e) => { e.preventDefault(); onToggleFavorite(); }}
            className="absolute right-3 top-3 rounded-md border border-white/15 bg-slate-950/62 p-2 text-white/70 shadow-[0_10px_26px_rgba(15,23,42,0.28)] backdrop-blur-md transition hover:bg-white hover:text-rose-500"
            aria-label={isFavorited ? t("mod.unfavorite") : t("mod.favorite")}
          >
            <Heart
              size={18}
              className={isFavorited ? "fill-red-500 text-red-500" : ""}
            />
          </button>
        )}
      </div>

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
      {introductionOpen && (
        <ModalShell
          open={introductionOpen}
          onClose={() => setIntroductionOpen(false)}
          size="md"
          panelClassName="max-h-[80vh] overflow-hidden"
        >
          <ModalHeader
            title={t("mod.aiIntroduction")}
            subtitle={<span className="line-clamp-1">{displayTitle}</span>}
            onClose={() => setIntroductionOpen(false)}
            closeAriaLabel={t("common.close")}
            className="px-5 py-3 border-b border-gray-200 shrink-0 mb-0"
          />
            <div className="max-h-[62vh] overflow-y-auto px-5 py-4">
              {generatingIntroduction && !introduction ? (
                <p className="text-sm text-gray-500">{t("mod.aiIntroductionLoading")}</p>
              ) : introError ? (
                <p className="text-sm text-red-600">{introError}</p>
              ) : (
                <p className="whitespace-pre-wrap text-sm leading-6 text-gray-700">{introduction || mod.ai_introduction || t("mod.noAiIntroduction")}</p>
              )}
            </div>
        </ModalShell>
      )}
    </Panel>
  );
};
