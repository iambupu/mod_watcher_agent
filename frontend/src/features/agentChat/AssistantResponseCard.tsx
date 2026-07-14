import React from "react";

import type { AgentModMatch } from "@/api/agent";
import { MarkdownText } from "@/components/MarkdownText";
import { extractAssistantSections } from "./responseCards";
import { AssistantNextSteps, AssistantSectionList } from "./AssistantResponseSections";
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

  const shouldShowAnswerBody = Boolean(responseCards && text.trim());

  return (
    <div className="space-y-3 text-[14px]">
      {shouldShowAnswerBody && (
        <MarkdownText
          text={text}
          className="rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800"
        />
      )}

      <AssistantSectionList sections={sections} />
      <AssistantNextSteps
        nextSteps={sections.nextSteps}
        expandOnlineCandidates={expandOnlineCandidates}
        expandOnlineCandidateDetails={expandOnlineCandidateDetails}
        narrowScopeFields={narrowScopeFields}
        reviewTargets={reviewTargets}
        conflictFields={conflictFields}
        onSelectNextStep={onSelectNextStep}
        onApplyScopeField={onApplyScopeField}
        onApplyReviewTarget={onApplyReviewTarget}
        onApplyConflictField={onApplyConflictField}
        onApplySourceCandidate={onApplySourceCandidate}
      />
    </div>
  );
};
