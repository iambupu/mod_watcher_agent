import { get, post } from "./client";

export interface AgentModMatch {
  id: number;
  title: string;
  translated_title_zh?: string;
  source: string;
  game: string;
  game_domain?: string;
  category?: string;
  author?: string;
  version?: string;
  url: string;
  updated_at_remote?: string;
  downloads?: number;
  endorsements?: number;
  likes?: number;
  adult_content?: boolean;
  score: number;
  score_breakdown?: Record<string, number>;
  rank_reason?: string;
  original_summary?: string;
  translated_summary?: string;
}

export interface AgentHistoryItem {
  role: "user" | "assistant";
  text: string;
}

interface AgentActionCandidate {
  id: string;
  label: string;
}

interface AgentActionPayload {
  expand_online_candidates?: AgentActionCandidate[];
  narrow_scope_fields?: string[];
  review_targets?: string[];
  conflict_fields?: string[];
  requires_user_confirmation?: boolean;
  [key: string]: unknown;
}

interface AgentWebSearchEvidence {
  enabled: boolean;
  queried: boolean;
  tools: string[];
  tool_statuses?: Record<string, string>;
  tool_result_counts?: Record<string, number>;
  succeeded_count?: number;
  skipped_count?: number;
  degraded_count?: number;
  online_result_count?: number;
  adaptation_triggered?: boolean;
  trigger_reasons?: string[];
}

export interface AgentAudit {
  analysis?: Record<string, unknown>;
  evidence?: {
    web_search?: AgentWebSearchEvidence;
    [key: string]: unknown;
  };
  conclusion?: {
    used_llm?: boolean;
    match_count?: number;
    consistency_risk?: "low" | "medium" | "high";
    recommended_action?: string;
    recommended_action_reason?: string;
    tool_policy_confidence?: "low" | "medium" | "high" | "unknown";
    evidence_sufficiency?: "insufficient" | "partial" | "sufficient";
    contract_status?: "ok" | "violated";
    contract_violations_count?: number;
    expand_online_candidates?: string[];
    expand_online_candidates_detail?: AgentActionCandidate[];
    action_payload?: AgentActionPayload;
    requires_clarification?: boolean;
    [key: string]: unknown;
  };
}

export interface AgentResponseCards {
  analysis?: string[];
  evidence?: string[];
  conclusion?: string[];
  understanding?: string[];
  filters?: string[];
  results?: string[];
  next_steps?: string[];
}

export interface AgentConversationMessage {
  id: string;
  role: "user" | "assistant" | "separator";
  text: string;
  session_id: string;
  created_at?: string;
  matches?: AgentModMatch[];
  response_cards?: AgentResponseCards;
  llm_provider?: string;
  llm_model?: string;
  audit?: AgentAudit;
}

export interface AgentChatResponse {
  answer: string;
  used_llm: boolean;
  matches: AgentModMatch[];
  response_cards?: AgentResponseCards;
  llm_provider?: string;
  llm_model?: string;
  audit?: AgentAudit;
}

export interface AgentModelOverride {
  providerOverride?: string;
  modelOverride?: string;
}

export interface AgentConversationState {
  messages: AgentConversationMessage[];
  active_session_id: string;
}

export function chatWithAgent(
  message: string,
  history: AgentHistoryItem[] = [],
  modelOverride?: AgentModelOverride,
) {
  return post<AgentChatResponse>("/agent/chat", {
    message,
    history,
    provider_override: modelOverride?.providerOverride,
    model_override: modelOverride?.modelOverride,
  });
}

export function askAgentModDetail(
  mod_id: number,
  question?: string,
  history: AgentHistoryItem[] = [],
  modelOverride?: AgentModelOverride,
) {
  return post<AgentChatResponse>("/agent/mod-detail", {
    mod_id,
    question,
    history,
    provider_override: modelOverride?.providerOverride,
    model_override: modelOverride?.modelOverride,
  });
}

export function fetchAgentConversationState() {
  return get<AgentConversationState>("/agent/conversation-state");
}

export function saveAgentConversationState(
  messages: AgentConversationMessage[],
  active_session_id: string,
  clientUpdatedAt?: string,
) {
  return post<AgentConversationState>("/agent/conversation-state", {
    messages,
    active_session_id,
    client_updated_at: clientUpdatedAt,
  });
}

export function startAgentConversation() {
  return post<{ session_id: string }>("/agent/conversation/new", {});
}
