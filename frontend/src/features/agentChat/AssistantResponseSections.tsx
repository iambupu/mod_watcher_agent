import React from "react";
import { useTranslation } from "react-i18next";

import type { AssistantSections, SourceCandidateDetail } from "./types";
import {
  conflictFieldQuestion,
  reviewTargetQuestion,
  scopeFieldQuestion,
  sourceCandidateLabel,
  sourceCandidateQuestion,
} from "./responseCards";

type SectionKey = Exclude<keyof AssistantSections, "nextSteps">;

const sectionStyles: Record<SectionKey, string> = {
  analysis: "border-slate-200 bg-white text-slate-700",
  evidence: "border-cyan-200 bg-cyan-50/60 text-cyan-700",
  conclusion: "border-cyan-200 bg-cyan-50/60 text-cyan-700",
  understanding: "border-sky-200 bg-sky-50/70 text-sky-700",
  filters: "border-sky-200 bg-sky-50/60 text-sky-700",
  results: "border-sky-200 bg-sky-50/60 text-sky-700",
};

interface AssistantSectionListProps {
  sections: AssistantSections;
}

export const AssistantSectionList: React.FC<AssistantSectionListProps> = ({ sections }) => {
  const { t } = useTranslation();
  return (Object.keys(sectionStyles) as SectionKey[]).map((key) => {
    const lines = sections[key];
    if (lines.length === 0) return null;
    return (
      <div key={key} className={`rounded-xl border px-3 py-2 ${sectionStyles[key]}`}>
        <p className="mb-1 text-[12px] font-semibold tracking-wide">{t(`agent.section.${key}`)}</p>
        <ul className="space-y-1 text-slate-800">
          {lines.map((line, index) => <li key={`${key}-${index}`} className="leading-6">{line}</li>)}
        </ul>
      </div>
    );
  });
};

interface ActionGroupProps {
  values: string[];
  question: (value: string) => string;
  onApply?: (value: string) => void;
}

const ActionGroup: React.FC<ActionGroupProps> = ({ values, question, onApply }) => {
  if (values.length === 0) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-2">
      {values.map((value) => (
        <button
          key={value}
          type="button"
          onClick={() => onApply?.(value)}
          className="rounded-md border border-amber-300 bg-white px-2 py-1 text-[12px] text-amber-700 transition hover:bg-amber-100"
        >
          {question(value)}
        </button>
      ))}
    </div>
  );
};

interface AssistantNextStepsProps {
  nextSteps: string[];
  expandOnlineCandidates: string[];
  expandOnlineCandidateDetails: SourceCandidateDetail[];
  narrowScopeFields: string[];
  reviewTargets: string[];
  conflictFields: string[];
  onSelectNextStep?: (value: string) => void;
  onApplyScopeField?: (field: string) => void;
  onApplyReviewTarget?: (target: string) => void;
  onApplyConflictField?: (field: string) => void;
  onApplySourceCandidate?: (candidate: string) => void;
}

export const AssistantNextSteps: React.FC<AssistantNextStepsProps> = ({
  nextSteps,
  expandOnlineCandidates,
  expandOnlineCandidateDetails,
  narrowScopeFields,
  reviewTargets,
  conflictFields,
  onSelectNextStep,
  onApplyScopeField,
  onApplyReviewTarget,
  onApplyConflictField,
  onApplySourceCandidate,
}) => {
  const { t } = useTranslation();
  const candidates = expandOnlineCandidateDetails.length > 0
    ? expandOnlineCandidateDetails
    : expandOnlineCandidates.map((candidate) => ({ id: candidate, label: sourceCandidateLabel(candidate) }));
  const hasActions = candidates.length + narrowScopeFields.length + reviewTargets.length + conflictFields.length > 0;
  if (nextSteps.length === 0 && !hasActions) return null;

  return (
    <div className="rounded-xl border border-amber-200 bg-amber-50/60 px-3 py-2">
      <p className="mb-1 text-[12px] font-semibold tracking-wide text-amber-700">{t("agent.section.nextSteps")}</p>
      {nextSteps.length > 0 && (
        <ul className="space-y-1 text-slate-800">
          {nextSteps.map((line, index) => (
            <li key={`next-${index}`}>
              <button type="button" onClick={() => onSelectNextStep?.(line)} className="w-full rounded-md px-1.5 py-1 text-left leading-6 transition hover:bg-amber-100/80 hover:text-amber-900 focus:outline-none focus:ring-2 focus:ring-amber-300">
                {line}
              </button>
            </li>
          ))}
        </ul>
      )}
      <ActionGroup values={candidates.map(({ id }) => id)} question={(id) => sourceCandidateQuestion(candidates.find((candidate) => candidate.id === id)?.label || id)} onApply={onApplySourceCandidate} />
      <ActionGroup values={narrowScopeFields} question={scopeFieldQuestion} onApply={onApplyScopeField} />
      <ActionGroup values={reviewTargets} question={reviewTargetQuestion} onApply={onApplyReviewTarget} />
      <ActionGroup values={conflictFields} question={conflictFieldQuestion} onApply={onApplyConflictField} />
    </div>
  );
};
