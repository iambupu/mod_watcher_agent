// 中文注释：说明 frontend/src/features/agentChat/AgentMatchCard.tsx 的前端模块职责，便于维护时快速定位。

import React, { useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, ChevronUp, Heart, HeartOff, Sparkles } from "lucide-react";

import type { AgentModMatch } from "@/api/agent";
import { Panel } from "@/components/ui/Panel";
import { useUIStore } from "@/stores/uiStore";
import { isAdultContent } from "@/utils/modAdult";
import { formatModSummary } from "@/utils/modSummary";
import { formatModTitle } from "@/utils/modTitle";

interface AgentMatchCardProps {
  item: AgentModMatch;
  isFavorited: boolean;
  onToggleFavorite: (modId: number, isFavorited: boolean) => void;
  onAskDetail: (mod: AgentModMatch) => void;
}

export const AgentMatchCard: React.FC<AgentMatchCardProps> = ({
  item,
  isFavorited,
  onToggleFavorite,
  onAskDetail,
}) => {
  const { t } = useTranslation();
  const summaryMode = useUIStore((s) => s.summaryMode);
  const [expanded, setExpanded] = useState(false);
  const displayTitle = formatModTitle(item, summaryMode);
  const translated = (item.translated_summary || "").trim();
  const original = (item.original_summary || "").trim();
  const summaryText = formatModSummary({
    original,
    translated,
    mode: summaryMode,
  }).trim();
  const matchReason = (item.rank_reason || "").trim();
  const description = summaryText || matchReason || t("mod.noSummary");
  const canToggleSummary = description.length > 120 || description.includes("\n\n");
  const sourceClass =
    item.source?.toLowerCase() === "nexusmods"
      ? "border-indigo-200 bg-indigo-50 text-indigo-700"
      : "border-slate-200 bg-slate-100 text-slate-700";
  const hasAdultFlag = item.adult_content !== null && item.adult_content !== undefined;
  const adultContent = isAdultContent(item.adult_content);
  const safetyLabel = hasAdultFlag ? (adultContent ? "NSFW" : "SFW") : "";
  const safetyClass =
    hasAdultFlag && adultContent
      ? "border-rose-200 bg-rose-50 text-rose-700"
      : hasAdultFlag
        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
        : "";

  return (
    <Panel padding="none" shadow="sm" radius="xl" className="p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="whitespace-pre-line text-[14px] font-semibold text-slate-900">{displayTitle}</div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${sourceClass}`}>
          {item.source}
        </span>
        <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600">
          {item.game}
        </span>
        {hasAdultFlag && (
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${safetyClass}`}>
            {safetyLabel}
          </span>
        )}
      </div>
      <div className="mt-1 text-[12px] text-slate-500">
        {item.author || "unknown"}
      </div>
      <div className="mt-2 space-y-1.5">
        {summaryText ? null : matchReason ? (
          <p className="text-[11px] font-medium text-slate-400">{t("agent.matchReason")}</p>
        ) : null}
        <p
          className={`mt-0.5 whitespace-pre-wrap text-[13px] leading-6 text-slate-700 ${
            expanded ? "" : "line-clamp-3"
          } ${summaryText || matchReason ? "" : "text-slate-400"}`}
        >
          {description}
        </p>
      </div>
      {canToggleSummary && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 inline-flex items-center gap-1 text-[12px] text-indigo-600 hover:text-indigo-700"
          title={expanded ? t("mod.collapseSummary") : t("mod.expandSummary")}
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          <span>{expanded ? t("mod.collapseSummary") : t("mod.expandSummary")}</span>
        </button>
      )}
      <div className="mt-2 flex items-center gap-3 text-[12px]">
        <button
          type="button"
          onClick={() => onToggleFavorite(item.id, isFavorited)}
          className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900"
          title={isFavorited ? t("mod.unfavorite") : t("mod.favorite")}
        >
          {isFavorited ? <HeartOff size={12} className="text-red-500" /> : <Heart size={12} className="text-gray-400" />}
          <span>{isFavorited ? t("mod.unfavorite") : t("mod.favorite")}</span>
        </button>
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-700"
          title={t("mod.openOriginal")}
        >
          <span>{t("mod.openOriginal")}</span>
        </a>
        <button
          type="button"
          onClick={() => onAskDetail(item)}
          className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-700"
          title={t("mod.detail")}
        >
          <Sparkles size={12} />
          <span>{t("mod.detail")}</span>
        </button>
      </div>
    </Panel>
  );
};
