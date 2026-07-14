import React from "react";
import { useTranslation } from "react-i18next";
import { Gamepad2, Heart, ImageIcon, ShieldAlert } from "lucide-react";

import { SourceBadge } from "@/components/SourceBadge";
import { isAdultContent } from "@/utils/modAdult";
import type { ModItem } from "@/types";

const sourceBadgeTone: Record<ModItem["source"], string> = {
  nexusmods: "border-cyan-300/70 bg-cyan-50/95 text-cyan-900 shadow-[0_8px_24px_rgba(8,145,178,0.16)]",
  loverslab: "border-sky-300/70 bg-sky-50/95 text-sky-900 shadow-[0_8px_24px_rgba(2,132,199,0.16)]",
};

interface ModCardMediaProps {
  mod: ModItem;
  displayTitle: string;
  gameLabel: string;
  isFavorited: boolean;
  onToggleFavorite?: () => void;
}

export const ModCardMedia: React.FC<ModCardMediaProps> = ({ mod, displayTitle, gameLabel, isFavorited, onToggleFavorite }) => {
  const { t } = useTranslation();
  return (
    <div className={`relative flex-shrink-0 overflow-hidden bg-slate-950 ${mod.thumbnail_url ? "aspect-[300/169]" : "aspect-[300/85]"}`}>
      {mod.thumbnail_url ? (
        <img src={mod.thumbnail_url} alt={displayTitle} className="absolute inset-0 h-full w-full object-cover transition duration-300 group-hover:scale-[1.025]" loading="lazy" decoding="async" />
      ) : (
        <div className="flex h-full w-full items-center justify-center bg-[radial-gradient(circle_at_top_left,rgba(56,189,248,0.22),transparent_34%),linear-gradient(135deg,#111827,#0f172a)] text-sky-100/55">
          <ImageIcon size={44} strokeWidth={1.35} />
        </div>
      )}
      <div className="absolute inset-0 bg-gradient-to-t from-slate-950/64 via-slate-950/5 to-slate-950/22" />
      <div className="pointer-events-none absolute inset-0 opacity-[0.06] [background-image:linear-gradient(rgba(255,255,255,0.28)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,0.28)_1px,transparent_1px)] [background-size:22px_22px]" />
      <div className="absolute left-3 top-3">
        <div className="flex max-w-[calc(100%-3rem)] flex-wrap gap-1.5">
          <SourceBadge source={mod.source} className={`backdrop-blur-md ${sourceBadgeTone[mod.source]}`} />
          {isAdultContent(mod.adult_content) && (
            <span className="inline-flex items-center gap-1 rounded-md border border-rose-300/70 bg-rose-50/95 px-2 py-0.5 text-xs font-semibold text-rose-800 shadow-[0_8px_24px_rgba(225,29,72,0.14)] backdrop-blur-md" title="Adult content">
              <ShieldAlert size={12} strokeWidth={2.2} /> NSFW
            </span>
          )}
        </div>
      </div>
      {gameLabel && (
        <div className="absolute bottom-3 left-3 right-3">
          <span className="inline-flex max-w-full items-center gap-1.5 rounded-md border border-white/35 bg-slate-950/90 px-2.5 py-1 text-xs font-semibold text-white shadow-[0_12px_28px_rgba(2,6,23,0.46)] ring-1 ring-black/35 backdrop-blur-sm [text-shadow:0_1px_2px_rgba(0,0,0,0.72)]" title={gameLabel}>
            <Gamepad2 size={13} strokeWidth={2.2} /><span className="truncate">{gameLabel}</span>
          </span>
        </div>
      )}
      {onToggleFavorite && (
        <button onClick={(event) => { event.preventDefault(); onToggleFavorite(); }} className="absolute right-3 top-3 rounded-md border border-white/15 bg-slate-950/62 p-2 text-white/70 shadow-[0_10px_26px_rgba(15,23,42,0.28)] backdrop-blur-md transition hover:bg-white hover:text-rose-500" aria-label={isFavorited ? t("mod.unfavorite") : t("mod.favorite")}>
          <Heart size={18} className={isFavorited ? "fill-red-500 text-red-500" : ""} />
        </button>
      )}
    </div>
  );
};
