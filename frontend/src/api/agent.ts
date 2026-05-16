import { get, post } from "./client";

export interface AgentModMatch {
  id: number;
  title: string;
  source: string;
  game: string;
  author?: string;
  version?: string;
  url: string;
  updated_at_remote?: string;
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
}

export interface AgentChatResponse {
  answer: string;
  used_llm: boolean;
  matches: AgentModMatch[];
}

export interface AgentConversationState {
  messages: AgentConversationMessage[];
  active_session_id: string;
}

export function chatWithAgent(message: string, history: AgentHistoryItem[] = []) {
  return post<AgentChatResponse>("/agent/chat", { message, history });
}

export function askAgentModDetail(mod_id: number, question?: string, history: AgentHistoryItem[] = []) {
  return post<AgentChatResponse>("/agent/mod-detail", { mod_id, question, history });
}

export function fetchAgentConversationState() {
  return get<AgentConversationState>("/agent/conversation-state");
}

export function saveAgentConversationState(messages: AgentConversationMessage[], active_session_id: string) {
  return post<AgentConversationState>("/agent/conversation-state", { messages, active_session_id });
}

export function startAgentConversation() {
  return post<{ session_id: string }>("/agent/conversation/new", {});
}
