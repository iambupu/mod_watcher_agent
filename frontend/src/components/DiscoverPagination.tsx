import React from "react";
import { useTranslation } from "react-i18next";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { Button } from "@/components/ui/Button";
import { parseIntegerInput } from "@/utils/numberInput";

interface DiscoverPaginationProps {
  page: number;
  totalPages: number;
  pageInput: string;
  onPageInputChange: (value: string) => void;
  onPageChange: (page: number) => void;
}

function visiblePages(page: number, totalPages: number): { pages: number[]; start: number; end: number } {
  const maxVisible = 5;
  let start = Math.max(1, page - Math.floor(maxVisible / 2));
  let end = Math.min(totalPages, start + maxVisible - 1);
  if (end - start + 1 < maxVisible) start = Math.max(1, end - maxVisible + 1);
  return { pages: Array.from({ length: end - start + 1 }, (_, index) => start + index), start, end };
}

export const DiscoverPagination: React.FC<DiscoverPaginationProps> = ({ page, totalPages, pageInput, onPageInputChange, onPageChange }) => {
  const { t } = useTranslation();
  if (totalPages <= 1) return null;
  const { pages, start, end } = visiblePages(page, totalPages);
  const jumpToPage = () => {
    const target = parseIntegerInput(pageInput, { min: 1, max: totalPages });
    onPageInputChange(String(target ?? page));
    if (target !== null && target !== undefined && target !== page) onPageChange(target);
  };

  return (
    <div className="mt-8 flex flex-wrap items-center justify-center gap-2 rounded-xl border border-slate-200 bg-white px-3 py-3 shadow-sm">
      <Button variant="outline" size="sm" className="border-slate-200 bg-white text-slate-700 hover:bg-slate-50" disabled={page <= 1} onClick={() => onPageChange(page - 1)}><ChevronLeft size={16} /></Button>
      {start > 1 && <><Button variant="ghost" size="sm" className="text-slate-600 hover:bg-slate-100 hover:text-slate-950" onClick={() => onPageChange(1)}>1</Button>{start > 2 && <span className="px-1 text-slate-400">...</span>}</>}
      {pages.map((value) => <Button key={value} variant={value === page ? "default" : "ghost"} size="sm" className={value === page ? "border border-sky-200 bg-sky-100 text-sky-800 hover:bg-sky-100" : "text-slate-600 hover:bg-slate-100 hover:text-slate-950"} onClick={() => onPageChange(value)}>{value}</Button>)}
      {end < totalPages && <>{end < totalPages - 1 && <span className="px-1 text-slate-400">...</span>}<Button variant="ghost" size="sm" className="text-slate-600 hover:bg-slate-100 hover:text-slate-950" onClick={() => onPageChange(totalPages)}>{totalPages}</Button></>}
      <Button variant="outline" size="sm" className="border-slate-200 bg-white text-slate-700 hover:bg-slate-50" disabled={page >= totalPages} onClick={() => onPageChange(page + 1)}><ChevronRight size={16} /></Button>
      <div className="ml-2 inline-flex items-center gap-2">
        <input type="number" min={1} max={totalPages} value={pageInput} onChange={(event) => onPageInputChange(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter") jumpToPage(); }} className="h-9 w-24 rounded-md border border-slate-200 bg-white px-2 text-sm font-semibold text-slate-700 outline-none focus:border-sky-500 focus:ring-2 focus:ring-sky-100" aria-label={t("discover.pageJumpInputLabel")} />
        <Button type="button" variant="outline" size="sm" className="border-slate-200 bg-white text-slate-700 hover:bg-slate-50" onClick={jumpToPage}>{t("discover.pageJumpAction")}</Button>
      </div>
    </div>
  );
};
