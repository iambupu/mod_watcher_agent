import { useEffect, useRef, type Dispatch, type SetStateAction } from "react";
import { useMutation } from "@tanstack/react-query";

import {
  saveAgentConversationState,
  type AgentConversationMessage,
  type AgentConversationState,
} from "@/api/agent";
import { ApiError } from "@/api/client";
import { toApiResponseCards, toChatResponseCards } from "@/features/agentChat/responseCards";
import type { ChatMessage } from "@/features/agentChat/types";

type PendingConversationSave = {
  data: ChatMessage[];
  sessionId: string;
  clientUpdatedAt: string;
};

type ConversationRefetchResult = {
  data?: AgentConversationState;
};

interface UseAgentConversationPersistenceArgs {
  messages: ChatMessage[];
  setMessages: Dispatch<SetStateAction<ChatMessage[]>>;
  activeSessionId: string;
  setActiveSessionId: Dispatch<SetStateAction<string>>;
  conversationState: AgentConversationState | undefined;
  conversationStateLoading: boolean;
  refetchConversationState: () => Promise<ConversationRefetchResult>;
  welcomeText: string;
}

function isApiStatus(error: unknown, status: number): boolean {
  return error instanceof ApiError
    ? error.status === status
    : typeof error === "object" && error !== null && "status" in error && (error as { status?: unknown }).status === status;
}

export function useAgentConversationPersistence({
  messages,
  setMessages,
  activeSessionId,
  setActiveSessionId,
  conversationState,
  conversationStateLoading,
  refetchConversationState,
  welcomeText,
}: UseAgentConversationPersistenceArgs) {
  const activeSessionIdRef = useRef("");
  const loadedRef = useRef(false);
  const saveTimerRef = useRef<number | null>(null);
  const saveRetryTimerRef = useRef<number | null>(null);
  const savingRef = useRef(false);
  const pendingSavesRef = useRef<Map<string, PendingConversationSave>>(new Map());
  const conflictedSessionIdsRef = useRef<Set<string>>(new Set());

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  const createWelcomeMessage = (sessionId: string, id = "welcome"): ChatMessage => ({
    id,
    role: "assistant",
    text: welcomeText,
    sessionId,
  });

  const applyConversationState = (state: AgentConversationState | undefined) => {
    if (state && state.messages.length > 0) {
      const activeConversationId = state.active_session_id || state.messages[state.messages.length - 1]?.session_id || `sess_${Date.now()}`;
      const currentMessages = state.messages
        .map((message) => ({
          id: message.id,
          role: message.role,
          text: message.text,
          sessionId: message.session_id,
          createdAt: message.created_at,
          matches: message.matches,
          responseCards: toChatResponseCards(message.response_cards),
          llmProvider: message.llm_provider,
          llmModel: message.llm_model,
          audit: message.audit,
        }))
        .filter((message) => message.sessionId === activeConversationId && message.role !== "separator");
      const firstWelcomeIndex = currentMessages.findIndex((message) => message.role === "assistant" && message.text === welcomeText);
      const dedupedMessages = currentMessages.filter(
        (message, index) => !(message.role === "assistant" && message.text === welcomeText && index !== firstWelcomeIndex),
      );
      setActiveSessionId(activeConversationId);
      setMessages(dedupedMessages.length > 0 ? dedupedMessages : [createWelcomeMessage(activeConversationId)]);
      return;
    }
    const initialSessionId = state?.active_session_id || `sess_${Date.now()}`;
    setActiveSessionId(initialSessionId);
    setMessages([createWelcomeMessage(initialSessionId)]);
  };

  useEffect(() => {
    if (loadedRef.current || conversationStateLoading) return;
    loadedRef.current = true;
    applyConversationState(conversationState);
  }, [conversationState, conversationStateLoading, welcomeText]);

  const saveConversationMutation = useMutation({
    mutationFn: ({ data, sessionId, clientUpdatedAt }: PendingConversationSave) => {
      const payload: AgentConversationMessage[] = data.slice(-300).map((message) => ({
        id: message.id,
        role: message.role,
        text: message.text,
        session_id: message.sessionId,
        created_at: message.createdAt,
        matches: message.matches,
        response_cards: toApiResponseCards(message.responseCards),
        llm_provider: message.llmProvider,
        llm_model: message.llmModel,
        audit: message.audit,
      }));
      return saveAgentConversationState(payload, sessionId, clientUpdatedAt);
    },
  });

  const clearConversationMutation = useMutation({
    mutationFn: ({ sessionId, clientUpdatedAt }: { sessionId: string; clientUpdatedAt: string }) =>
      saveAgentConversationState([], sessionId, clientUpdatedAt),
  });

  const queuePendingSave = (sessionId: string, data: ChatMessage[], clientUpdatedAt = new Date().toISOString()) => {
    if (conflictedSessionIdsRef.current.has(sessionId)) return;
    pendingSavesRef.current.set(sessionId, { data, sessionId, clientUpdatedAt });
  };

  const queueActiveSessionSave = (sessionId = activeSessionId) => {
    if (!sessionId) return;
    const activeMessages = messages.filter((message) => message.sessionId === sessionId);
    queuePendingSave(sessionId, activeMessages);
  };

  const nextPendingSave = (): PendingConversationSave | null => {
    const next = pendingSavesRef.current.values().next();
    return next.done ? null : next.value;
  };

  const flushPendingSave = () => {
    if (savingRef.current) return;
    const snapshot = nextPendingSave();
    if (!snapshot) return;
    pendingSavesRef.current.delete(snapshot.sessionId);
    savingRef.current = true;
    saveConversationMutation.mutate(snapshot, {
      onSuccess: () => {
        savingRef.current = false;
        if (pendingSavesRef.current.size > 0) {
          flushPendingSave();
        }
      },
      onError: (error) => {
        savingRef.current = false;
        if (isApiStatus(error, 409)) {
          conflictedSessionIdsRef.current.add(snapshot.sessionId);
          pendingSavesRef.current.delete(snapshot.sessionId);
          void refetchConversationState()
            .then(({ data }) => {
              conflictedSessionIdsRef.current.delete(snapshot.sessionId);
              loadedRef.current = true;
              applyConversationState(data);
            })
            .catch(() => undefined);
          if (pendingSavesRef.current.size > 0) {
            flushPendingSave();
          }
          return;
        }
        if (!pendingSavesRef.current.has(snapshot.sessionId)) {
          pendingSavesRef.current.set(snapshot.sessionId, snapshot);
        }
        if (saveRetryTimerRef.current) {
          window.clearTimeout(saveRetryTimerRef.current);
        }
        saveRetryTimerRef.current = window.setTimeout(() => {
          saveRetryTimerRef.current = null;
          flushPendingSave();
        }, 1000);
      },
    });
  };

  useEffect(() => {
    if (!loadedRef.current || !activeSessionId) return;
    const activeMessages = messages.filter((message) => message.sessionId === activeSessionId);
    queuePendingSave(activeSessionId, activeMessages);
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
    }
    saveTimerRef.current = window.setTimeout(() => {
      flushPendingSave();
    }, 300);
  }, [messages, activeSessionId]);

  useEffect(() => {
    return () => {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
      }
      if (saveRetryTimerRef.current) {
        window.clearTimeout(saveRetryTimerRef.current);
      }
    };
  }, []);

  const clearConversation = async (sessionId: string) => {
    if (saveTimerRef.current) {
      window.clearTimeout(saveTimerRef.current);
      saveTimerRef.current = null;
    }
    pendingSavesRef.current.delete(sessionId);
    conflictedSessionIdsRef.current.delete(sessionId);
    await clearConversationMutation.mutateAsync({
      sessionId,
      clientUpdatedAt: new Date().toISOString(),
    });
  };

  return {
    activeSessionIdRef,
    createWelcomeMessage,
    queueActiveSessionSave,
    flushPendingSave,
    clearConversation,
    clearConversationPending: clearConversationMutation.isPending,
  };
}
