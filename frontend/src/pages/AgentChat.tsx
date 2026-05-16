import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Send,
  Loader2,
  Copy,
  Check,
  ChevronDown,
  ChevronUp,
  Heart,
  HeartOff,
  Sparkles,
  Plus,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import {
  askAgentModDetail,
  chatWithAgent,
  fetchAgentConversationState,
  saveAgentConversationState,
  startAgentConversation,
  type AgentConversationMessage,
  type AgentHistoryItem,
  type AgentModMatch,
} from "@/api/agent";
import { addFavorite, fetchFavorites, removeFavorite } from "@/api/favorites";
import AppSidebar from "@/components/layout/AppSidebar";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "separator";
  text: string;
  sessionId: string;
  createdAt?: string;
  matches?: AgentModMatch[];
}

const AgentMatchCard: React.FC<{
  item: AgentModMatch;
  isFavorited: boolean;
  onToggleFavorite: (modId: number, isFavorited: boolean) => void;
  onAskDetail: (mod: AgentModMatch) => void;
}> = ({ item, isFavorited, onToggleFavorite, onAskDetail }) => {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);
  const translated = (item.translated_summary || "").trim();
  const original = (item.original_summary || "").trim();
  const hasSummary = Boolean(translated || original);
  const mergedSummary = [translated, original].filter(Boolean).join("\n");
  const canToggleSummary = mergedSummary.length > 120 || mergedSummary.includes("\n\n");

  return (
    <div className="rounded-md border border-gray-200 bg-gray-50 p-2.5">
      <div className="text-sm font-medium text-gray-900">{item.title}</div>
      <div className="text-xs text-gray-500">
        {item.source} · {item.game} · {item.author || "unknown"}
      </div>
      {hasSummary && (
        <div className="mt-2 space-y-1.5">
          <p
            className={`mt-0.5 text-xs leading-5 text-gray-700 whitespace-pre-wrap ${
              expanded ? "" : "line-clamp-3"
            }`}
          >
            {expanded ? mergedSummary : mergedSummary}
          </p>
        </div>
      )}
      {hasSummary && canToggleSummary && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-2 inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-700"
          title={expanded ? t("mod.collapseSummary") : t("mod.expandSummary")}
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          <span>{expanded ? t("mod.collapseSummary") : t("mod.expandSummary")}</span>
        </button>
      )}
      <div className="mt-2 flex items-center gap-3 text-xs">
        <button
          type="button"
          onClick={() => onToggleFavorite(item.id, isFavorited)}
          className="inline-flex items-center gap-1 text-gray-600 hover:text-gray-900"
          title={isFavorited ? t("mod.unfavorite") : t("mod.favorite")}
        >
          {isFavorited ? <HeartOff size={12} className="text-red-500" /> : <Heart size={12} className="text-gray-400" />}
          <span>{isFavorited ? t("mod.unfavorite") : t("mod.favorite")}</span>
        </button>
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-700"
          title={t("mod.openOriginal")}
        >
          <span>{t("mod.openOriginal")}</span>
        </a>
        <button
          type="button"
          onClick={() => onAskDetail(item)}
          className="inline-flex items-center gap-1 text-blue-600 hover:text-blue-700"
          title={t("mod.detail")}
        >
          <Sparkles size={12} />
          <span>{t("mod.detail")}</span>
        </button>
      </div>
    </div>
  );
};

const AgentChat: React.FC = () => {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [copiedId, setCopiedId] = useState<string>("");
  const viewportRef = useRef<HTMLDivElement>(null);
  const loadedRef = useRef(false);
  const saveTimerRef = useRef<number | null>(null);
  const savingRef = useRef(false);
  const pendingSaveRef = useRef<{ data: ChatMessage[]; sessionId: string } | null>(null);

  const favoritesQuery = useQuery({
    queryKey: ["favorites"],
    queryFn: fetchFavorites,
    staleTime: 30_000,
  });
  const favoriteByModId = useMemo(() => {
    const map = new Map<number, number>();
    for (const fav of favoritesQuery.data || []) {
      map.set(fav.modId, fav.id);
    }
    return map;
  }, [favoritesQuery.data]);

  const conversationQuery = useQuery({
    queryKey: ["agent-conversation-state"],
    queryFn: fetchAgentConversationState,
  });

  useEffect(() => {
    if (loadedRef.current || conversationQuery.isLoading) return;
    loadedRef.current = true;
    const state = conversationQuery.data;
    if (state && state.messages.length > 0) {
      setMessages(
        state.messages.map((m) => ({
          id: m.id,
          role: m.role,
          text: m.text,
          sessionId: m.session_id,
          createdAt: m.created_at,
          matches: m.matches,
        })),
      );
      setActiveSessionId(state.active_session_id);
      return;
    }
    const initialSessionId = state?.active_session_id || `sess_${Date.now()}`;
    setActiveSessionId(initialSessionId);
    setMessages([
      { id: "welcome", role: "assistant", text: t("agent.hint"), sessionId: initialSessionId },
    ]);
  }, [conversationQuery.data, conversationQuery.isLoading, t]);

  const saveConversationMutation = useMutation({
    mutationFn: ({ data, sessionId }: { data: ChatMessage[]; sessionId: string }) => {
      const payload: AgentConversationMessage[] = data.slice(-300).map((m) => ({
        id: m.id,
        role: m.role,
        text: m.text,
        session_id: m.sessionId,
        created_at: m.createdAt,
        matches: m.matches,
      }));
      return saveAgentConversationState(payload, sessionId);
    },
  });

  const flushPendingSave = () => {
    if (savingRef.current) return;
    const snapshot = pendingSaveRef.current;
    if (!snapshot) return;
    pendingSaveRef.current = null;
    savingRef.current = true;
    saveConversationMutation.mutate(snapshot, {
      onSettled: () => {
        savingRef.current = false;
        if (pendingSaveRef.current) {
          flushPendingSave();
        }
      },
    });
  };

  useEffect(() => {
    if (!loadedRef.current || !activeSessionId) return;
    pendingSaveRef.current = { data: messages, sessionId: activeSessionId };
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
    };
  }, []);

  const buildHistory = (list: ChatMessage[]): AgentHistoryItem[] =>
    list
      .filter(
        (m): m is ChatMessage & { role: "user" | "assistant" } =>
          (m.role === "user" || m.role === "assistant") && m.sessionId === activeSessionId,
      )
      .map((m) => ({ role: m.role, text: m.text }))
      .slice(-40);

  const mutation = useMutation({
    mutationFn: ({ message, history }: { message: string; history: AgentHistoryItem[] }) => chatWithAgent(message, history),
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          text: data.answer,
          sessionId: activeSessionId,
          matches: data.matches,
        },
      ]);
      setTimeout(() => {
        viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: "smooth" });
      }, 30);
    },
    onError: (error) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant-error`,
          role: "assistant",
          text: (error as Error).message,
          sessionId: activeSessionId,
        },
      ]);
    },
  });

  const onSubmit = () => {
    const message = input.trim();
    if (!message) return;
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-user`, role: "user", text: message, sessionId: activeSessionId },
    ]);
    setInput("");
    mutation.mutate({
      message,
      history: buildHistory(messages),
    });
    setTimeout(() => {
      viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: "smooth" });
    }, 30);
  };

  const toggleFavoriteMutation = useMutation({
    mutationFn: async ({ modId, isFavorited }: { modId: number; isFavorited: boolean }) => {
      if (isFavorited) {
        const favId = favoriteByModId.get(modId);
        if (!favId) return;
        await removeFavorite(favId);
      } else {
        await addFavorite({ mod_id: modId });
      }
    },
    onSuccess: () => favoritesQuery.refetch(),
  });

  const detailMutation = useMutation({
    mutationFn: ({ modId, question, history }: { modId: number; question?: string; history: AgentHistoryItem[] }) =>
      askAgentModDetail(modId, question, history),
    onSuccess: (data) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant-detail`,
          role: "assistant",
          text: data.answer,
          sessionId: activeSessionId,
          matches: data.matches,
        },
      ]);
      setTimeout(() => {
        viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: "smooth" });
      }, 30);
    },
  });

  const onAskDetail = (mod: AgentModMatch) => {
    const askText = `请详细解析这个 Mod：${mod.title}`;
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-user-detail`, role: "user", text: askText, sessionId: activeSessionId },
    ]);
    detailMutation.mutate({
      modId: mod.id,
      question: askText,
      history: buildHistory(messages),
    });
  };

  const copyMessage = async (id: string, text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => setCopiedId(""), 1000);
    } catch {
      setCopiedId("");
    }
  };

  const handleStartNewConversation = async () => {
    const res = await startAgentConversation();
    const nextSessionId = res.session_id;
    setActiveSessionId(nextSessionId);
    setMessages((prev) => [
      ...prev,
      {
        id: `${Date.now()}-separator`,
        role: "separator",
        text: `新对话 ${new Date().toLocaleString()}`,
        sessionId: nextSessionId,
      },
    ]);
  };

  return (
    <div className="min-h-screen bg-gray-50">
      <div className="flex h-screen">
        <AppSidebar active="agent" />

        <main className="flex-1 flex flex-col min-h-0">
          <div className="px-6 py-4 border-b border-gray-200 bg-white">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold text-gray-900">{t("agent.title")}</h2>
              <button
                type="button"
                onClick={handleStartNewConversation}
                className="inline-flex items-center gap-1 rounded-md border border-gray-300 px-2.5 py-1.5 text-xs text-gray-700 hover:bg-gray-50"
              >
                <Plus size={12} />
                开始新对话
              </button>
            </div>
          </div>

          <div ref={viewportRef} className="flex-1 overflow-y-auto p-6">
            <div className="max-w-4xl mx-auto space-y-4">
              {messages.map((msg) => (
                <div key={msg.id}>
                  {msg.role === "separator" ? (
                    <div className="py-2">
                      <div className="flex items-center gap-2 text-xs text-gray-400">
                        <div className="h-px flex-1 bg-gray-200" />
                        <span>{msg.text}</span>
                        <div className="h-px flex-1 bg-gray-200" />
                      </div>
                    </div>
                  ) : (
                <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
                  <div
                    className={`max-w-[80%] rounded-2xl px-4 py-3 shadow-sm ${
                      msg.role === "user"
                        ? "bg-blue-600 text-white"
                        : "bg-white border border-gray-200 text-gray-900"
                    }`}
                  >
                    <div className="whitespace-pre-wrap text-sm">{msg.text}</div>
                    {msg.matches && msg.matches.length > 0 && (
                      <div className="mt-3 space-y-2">
                        {msg.matches.map((item) => (
                          <AgentMatchCard
                            key={item.id}
                            item={item}
                            isFavorited={favoriteByModId.has(item.id)}
                            onToggleFavorite={(modId, isFavorited) =>
                              toggleFavoriteMutation.mutate({ modId, isFavorited })
                            }
                            onAskDetail={onAskDetail}
                          />
                        ))}
                      </div>
                    )}
                    <button
                      type="button"
                      onClick={() => copyMessage(msg.id, msg.text)}
                      className={`mt-2 inline-flex items-center gap-1 text-xs ${
                        msg.role === "user" ? "text-blue-100 hover:text-white" : "text-gray-500 hover:text-gray-700"
                      }`}
                    >
                      {copiedId === msg.id ? <Check size={12} /> : <Copy size={12} />}
                      {copiedId === msg.id ? t("agent.copied") : t("agent.copy")}
                    </button>
                  </div>
                </div>
                  )}
                </div>
              ))}
              {(mutation.isPending || detailMutation.isPending) && (
                <div className="flex justify-start">
                  <div className="rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm text-gray-500 inline-flex items-center gap-2">
                    <Loader2 size={14} className="animate-spin" />
                    {t("common.loading")}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="border-t border-gray-200 bg-white p-4">
            <div className="max-w-4xl mx-auto">
              <div className="flex gap-2">
                <input
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onSubmit();
                  }}
                  placeholder={t("agent.placeholder")}
                  className="flex-1 rounded-md border border-gray-300 px-3 py-2 text-sm"
                />
                <Button onClick={onSubmit} disabled={mutation.isPending || detailMutation.isPending}>
                  <Send size={14} />
                </Button>
              </div>
            </div>
          </div>
        </main>
      </div>
    </div>
  );
};

export default AgentChat;
