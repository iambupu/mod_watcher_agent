// 中文注释：提供 HelpButton 业务组件。

import { useState, useRef, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { X } from "lucide-react";

interface HelpButtonProps {
  titleKey: string;
  stepsKey: string;
  stepCount: number;
}

export const HelpButton: React.FC<HelpButtonProps> = ({ titleKey, stepsKey, stepCount }) => {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen(!open)}
        className="inline-flex items-center justify-center w-5 h-5 rounded-full border border-gray-300 text-xs font-bold text-gray-500 hover:bg-gray-100 hover:text-gray-700 hover:border-gray-400 transition-colors leading-none"
        aria-label={t(titleKey)}
      >
        ?
      </button>
      {open && (
        <div className="absolute left-6 top-0 z-50 w-80 bg-white border border-gray-200 rounded-lg shadow-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <h4 className="text-sm font-semibold text-gray-800">{t(titleKey)}</h4>
            <button
              type="button"
              onClick={() => setOpen(false)}
              className="text-gray-400 hover:text-gray-600 transition-colors"
            >
              <X size={14} />
            </button>
          </div>
          <ol className="space-y-2">
            {Array.from({ length: stepCount }, (_, i) => (
              <li key={i} className="flex gap-2 text-sm text-gray-600">
                <span className="flex-shrink-0 w-5 h-5 rounded-full bg-gray-100 flex items-center justify-center text-xs font-medium text-gray-500">
                  {i + 1}
                </span>
                <span>{t(`${stepsKey}.${i + 1}`)}</span>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  );
};
