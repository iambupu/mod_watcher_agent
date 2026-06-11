// 中文注释：说明 frontend/src/features/agentChat/types.ts 的前端模块职责，便于维护时快速定位。

import type {
  AgentAudit,
  AgentConversationMessage,
  AgentModMatch,
  AgentResponseCards as ApiAgentResponseCards,
} from "@/api/agent";

export type ChatResponseCards = Omit<ApiAgentResponseCards, "next_steps"> & {
  nextSteps?: ApiAgentResponseCards["next_steps"];
};

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "separator";
  text: string;
  sessionId: string;
  createdAt?: string;
  matches?: AgentModMatch[];
  responseCards?: ChatResponseCards;
  llmProvider?: string;
  llmModel?: string;
  audit?: AgentAudit;
}

export interface AgentProviderDisplay {
  key: string;
  provider: string;
  model: string;
  label: string;
}

export interface AssistantSections {
  analysis: string[];
  evidence: string[];
  conclusion: string[];
  understanding: string[];
  filters: string[];
  results: string[];
  nextSteps: string[];
}

export type ApiResponseCards = AgentConversationMessage["response_cards"];
export type SourceCandidateDetail = { id: string; label: string };
