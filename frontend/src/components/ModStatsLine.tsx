import { Clock, Download, ThumbsUp } from "lucide-react";

interface ModStatsLineProps {
  downloads?: number | null;
  endorsements?: number | null;
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
  return (
    <div className={`flex flex-wrap items-center gap-3 text-xs ${className}`}>
      {downloads !== undefined && downloads !== null && (
        <span className="inline-flex items-center gap-1">
          <Download size={12} />
          {downloads.toLocaleString()}
        </span>
      )}
      {endorsements !== undefined && endorsements !== null && (
        <span className="inline-flex items-center gap-1">
          <ThumbsUp size={12} />
          {endorsements.toLocaleString()}
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
