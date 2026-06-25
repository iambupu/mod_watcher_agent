import React from "react";
import { useTranslation } from "react-i18next";

import type { AgentModMatch } from "@/api/agent";
import { MarkdownText } from "@/components/MarkdownText";
import {
  conflictFieldQuestion,
  extractAssistantSections,
  reviewTargetQuestion,
  scopeFieldQuestion,
  sourceCandidateLabel,
  sourceCandidateQuestion,
} from "./responseCards";
import type { ChatMessage, SourceCandidateDetail } from "./types";

interface AssistantResponseCardProps {
  text: string;
  matches?: AgentModMatch[];
  responseCards?: ChatMessage["responseCards"];
  onSelectNextStep?: (value: string) => void;
  expandOnlineCandidates?: string[];
  expandOnlineCandidateDetails?: SourceCandidateDetail[];
  narrowScopeFields?: string[];
  reviewTargets?: string[];
  conflictFields?: string[];
  onApplyScopeField?: (field: string) => void;
  onApplyReviewTarget?: (target: string) => void;
  onApplyConflictField?: (field: string) => void;
  onApplySourceCandidate?: (candidate: string) => void;
}

export const AssistantResponseCard: React.FC<AssistantResponseCardProps> = ({
  text,
  matches,
  responseCards,
  onSelectNextStep,
  expandOnlineCandidates = [],
  expandOnlineCandidateDetails = [],
  narrowScopeFields = [],
  reviewTargets = [],
  conflictFields = [],
  onApplyScopeField,
  onApplyReviewTarget,
  onApplyConflictField,
  onApplySourceCandidate,
}) => {
  const { t } = useTranslation();
  const sections = responseCards
    ? {
        analysis: responseCards.analysis || [],
        evidence: responseCards.evidence || [],
        conclusion: responseCards.conclusion || [],
        understanding: responseCards.understanding || [],
        filters: responseCards.filters || [],
        results: responseCards.results || [],
        nextSteps: responseCards.nextSteps || [],
      }
    : extractAssistantSections(text);

  if ((sections.results.length <= 1 || !responseCards) && (matches?.length || 0) > 1) {
    const preview = (matches || []).slice(0, 5).map((item, idx) => `${idx + 1}. ${item.title}`);
    sections.results = [`找到 ${matches?.length || 0} 个候选结果：`, ...preview];
  } else if (sections.results.length === 0 && (matches?.length || 0) === 1 && matches?.[0]) {
    sections.results = [`找到 1 个候选结果：`, `1. ${matches[0].title}`];
  }

  if (
    sections.analysis.length === 0 &&
    sections.evidence.length === 0 &&
    sections.conclusion.length === 0 &&
    sections.understanding.length === 0 &&
    sections.filters.length === 0 &&
    sections.results.length === 0 &&
    sections.nextSteps.length === 0
  ) {
    return <MarkdownText text={text} className="text-sm" />;
  }

  const sectionClass = "rounded-xl border px-3 py-2";
  const hasActionButtons =
    expandOnlineCandidateDetails.length > 0 ||
    expandOnlineCandidates.length > 0 ||
    narrowScopeFields.length > 0 ||
    reviewTargets.length > 0 ||
    conflictFields.length > 0;
  const shouldShowAnswerBody = Boolean(responseCards && text.trim());

  return (
    <div className="space-y-3 text-[14px]">
      {shouldShowAnswerBody && (
        <MarkdownText
          text={text}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
        />
      )}

      {sections.analysis.length > 0 && (
        <div className={`${sectionClass} border-slate-200 bg-white`}>
          <p className="mb-1 text-[12px] font-semibold tracking-wide text-slate-700">{t("agent.section.analysis")}</p>
          <ul className="space-y-1 text-slate-800">
            {sections.analysis.map((line, idx) => (
              <li key={`analysis-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        </div>
      )}

      {sections.evidence.length > 0 && (
        <div className={`${sectionClass} border-cyan-200 bg-cyan-50/60`}>
          <p className="mb-1 text-[12px] font-semibold tracking-wide text-cyan-700">{t("agent.section.evidence")}</p>
          <ul className="space-y-1 text-slate-800">
            {sections.evidence.map((line, idx) => (
              <li key={`evidence-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        </div>
      )}

      {sections.conclusion.length > 0 && (
        <div className={`${sectionClass} border-cyan-200 bg-cyan-50/60`}>
          <p className="mb-1 text-[12px] font-semibold tracking-wide text-cyan-700">{t("agent.section.conclusion")}</p>
          <ul className="space-y-1 text-slate-800">
            {sections.conclusion.map((line, idx) => (
              <li key={`conclusion-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        </div>
      )}

      {sections.understanding.length > 0 && (
        <div className={`${sectionClass} border-sky-200 bg-sky-50/70`}>
          <p className="mb-1 text-[12px] font-semibold tracking-wide text-sky-700">{t("agent.section.understanding")}</p>
          <ul className="space-y-1 text-slate-800">
            {sections.understanding.map((line, idx) => (
              <li key={`understanding-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        </div>
      )}

      {sections.filters.length > 0 && (
        <div className={`${sectionClass} border-sky-200 bg-sky-50/60`}>
          <p className="mb-1 text-[12px] font-semibold tracking-wide text-sky-700">{t("agent.section.filters")}</p>
          <ul className="space-y-1 text-slate-800">
            {sections.filters.map((line, idx) => (
              <li key={`filters-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        </div>
      )}

      {sections.results.length > 0 && (
        <div className={`${sectionClass} border-sky-200 bg-sky-50/60`}>
          <p className="mb-1 text-[12px] font-semibold tracking-wide text-sky-700">{t("agent.section.results")}</p>
          <ul className="space-y-1 text-slate-800">
            {sections.results.map((line, idx) => (
              <li key={`results-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        </div>
      )}

      {(sections.nextSteps.length > 0 || hasActionButtons) && (
        <div className={`${sectionClass} border-amber-200 bg-amber-50/60`}>
          <p className="mb-1 text-[12px] font-semibold tracking-wide text-amber-700">{t("agent.section.nextSteps")}</p>
          {sections.nextSteps.length > 0 && (
            <ul className="space-y-1 text-slate-800">
              {sections.nextSteps.map((line, idx) => (
                <li key={`next-${idx}`}>
                  <button
                    type="button"
                    onClick={() => onSelectNextStep?.(line)}
                    className="w-full rounded-md px-1.5 py-1 text-left leading-6 transition hover:bg-amber-100/80 hover:text-amber-900 focus:outline-none focus:ring-2 focus:ring-amber-300"
                  >
                    {line}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {(expandOnlineCandidateDetails.length > 0 || expandOnlineCandidates.length > 0) && (
            <div className="mt-2 flex flex-wrap gap-2">
              {(expandOnlineCandidateDetails.length > 0
                ? expandOnlineCandidateDetails
                : expandOnlineCandidates.map((candidate) => ({
                    id: candidate,
                    label: sourceCandidateLabel(candidate),
                  }))
              ).map((candidate) => (
                <button
                  key={candidate.id}
                  type="button"
                  onClick={() => onApplySourceCandidate?.(candidate.id)}
                  className="rounded-md border border-amber-300 bg-white px-2 py-1 text-[12px] text-amber-700 transition hover:bg-amber-100"
                >
                  {sourceCandidateQuestion(candidate.label)}
                </button>
              ))}
            </div>
          )}
          {narrowScopeFields.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {narrowScopeFields.map((field) => (
                <button
                  key={field}
                  type="button"
                  onClick={() => onApplyScopeField?.(field)}
                  className="rounded-md border border-amber-300 bg-white px-2 py-1 text-[12px] text-amber-700 transition hover:bg-amber-100"
                >
                  {scopeFieldQuestion(field)}
                </button>
              ))}
            </div>
          )}
          {reviewTargets.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {reviewTargets.map((target) => (
                <button
                  key={target}
                  type="button"
                  onClick={() => onApplyReviewTarget?.(target)}
                  className="rounded-md border border-amber-300 bg-white px-2 py-1 text-[12px] text-amber-700 transition hover:bg-amber-100"
                >
                  {reviewTargetQuestion(target)}
                </button>
              ))}
            </div>
          )}
          {conflictFields.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {conflictFields.map((field) => (
                <button
                  key={field}
                  type="button"
                  onClick={() => onApplyConflictField?.(field)}
                  className="rounded-md border border-amber-300 bg-white px-2 py-1 text-[12px] text-amber-700 transition hover:bg-amber-100"
                >
                  {conflictFieldQuestion(field)}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
