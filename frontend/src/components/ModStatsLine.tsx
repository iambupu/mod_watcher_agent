import { Clock, Download, ThumbsUp } from "lucide-react";
import { nonNegativeNumberValue } from "@/utils/numberInput";

interface ModStatsLineProps {
  downloads?: unknown;
  endorsements?: unknown;
  updatedAt?: string | null;
  className?: string;
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function ModStatsLine({
  downloads,
  endorsements,
  updatedAt,
  className = "text-slate-400",
}: ModStatsLineProps) {
  const downloadCount = nonNegativeNumberValue(downloads);
  const endorsementCount = nonNegativeNumberValue(endorsements);

  return (
    <div className={`flex flex-wrap items-center gap-3 text-xs ${className}`}>
      {downloadCount !== null && (
        <span className="inline-flex items-center gap-1">
          <Download size={12} />
          {downloadCount.toLocaleString()}
        </span>
      )}
      {endorsementCount !== null && (
        <span className="inline-flex items-center gap-1">
          <ThumbsUp size={12} />
          {endorsementCount.toLocaleString()}
        </span>
      )}
      {updatedAt && (
        <span className="inline-flex items-center gap-1">
          <Clock size={12} />
          {formatDate(updatedAt)}
        </span>
      )}
    </div>
  );
}
