import React from "react";
import { useTranslation } from "react-i18next";

import { ModalHeader, ModalShell } from "@/components/ui/Modal";

interface ModIntroductionModalProps {
  open: boolean;
  title: string;
  introduction: string;
  fallbackIntroduction?: string;
  error: string;
  loading: boolean;
  onClose: () => void;
}

export const ModIntroductionModal: React.FC<ModIntroductionModalProps> = ({ open, title, introduction, fallbackIntroduction, error, loading, onClose }) => {
  const { t } = useTranslation();
  return (
    <ModalShell open={open} onClose={onClose} size="md" panelClassName="max-h-[80vh] overflow-hidden">
      <ModalHeader title={t("mod.aiIntroduction")} subtitle={<span className="line-clamp-1">{title}</span>} onClose={onClose} closeAriaLabel={t("common.close")} className="mb-0 shrink-0 border-b border-gray-200 px-5 py-3" />
      <div className="max-h-[62vh] overflow-y-auto px-5 py-4">
        {loading && !introduction ? (
          <p className="text-sm text-gray-500">{t("mod.aiIntroductionLoading")}</p>
        ) : error ? (
          <p className="text-sm text-red-600">{error}</p>
        ) : (
          <p className="whitespace-pre-wrap text-sm leading-6 text-gray-700">{introduction || fallbackIntroduction || t("mod.noAiIntroduction")}</p>
        )}
      </div>
    </ModalShell>
  );
};
