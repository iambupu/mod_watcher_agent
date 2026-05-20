import { get, post } from "./client";

export interface AgentModMatch {
  id: number;
  title: string;
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
  original_summary?: string;
  translated_summary?: string;
}

export interface AgentHistoryItem {
  role: "user" | "assistant";
  text: string;
}

export interface AgentConversationMessage {
  id: string;
  role: "user" | "assistant" | "separator";
  text: string;
  session_id: string;
  created_at?: string;
  matches?: AgentModMatch[];
  response_cards?: {
    understanding?: string[];
    filters?: string[];
    results?: string[];
    next_steps?: string[];
  };
  llm_provider?: string;
  llm_model?: string;
}

export interface AgentChatResponse {
  answer: string;
  used_llm: boolean;
  matches: AgentModMatch[];
  response_cards?: {
    understanding?: string[];
    filters?: string[];
    results?: string[];
    next_steps?: string[];
  };
  llm_provider?: string;
  llm_model?: string;
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
