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
  Trash2,
  X,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { MarkdownText } from "@/components/MarkdownText";
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
import { fetchModGames } from "@/api/mods";
import AppSidebar from "@/components/layout/AppSidebar";
import { fetchSettings } from "@/api/settings";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "separator";
  text: string;
  sessionId: string;
  createdAt?: string;
  matches?: AgentModMatch[];
  responseCards?: {
    understanding?: string[];
    filters?: string[];
    results?: string[];
    nextSteps?: string[];
  };
  llmProvider?: string;
  llmModel?: string;
}

interface AgentProviderDisplay {
  key: string;
  provider: string;
  model: string;
  label: string;
}

interface AssistantSections {
  understanding: string[];
  filters: string[];
  results: string[];
  nextSteps: string[];
}

const extractAssistantSections = (text: string): AssistantSections => {
  const lines = text
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean);
  const sections: AssistantSections = {
    understanding: [],
    filters: [],
    results: [],
    nextSteps: [],
  };
  const normalize = (line: string) => line.replace(/^[•\-\d\.\)\(]+\s*/, "").trim();

  for (const line of lines) {
    const plain = normalize(line);
    if (!plain) continue;
    if (/^(我理解|理解你的需求|你想找|需求|目标|I understand|You want|理解しました)/i.test(plain)) {
      sections.understanding.push(plain);
      continue;
    }
    if (/^(游戏|類型|类型|時間|时间|来源|來源|source|game|type|filter|条件|條件|条件|來源|ソース)/i.test(plain)) {
      sections.filters.push(plain);
      continue;
    }
    if (/^(找到|命中|候选|候補|推荐|推薦|结果|結果|found|matched)/i.test(plain)) {
      sections.results.push(plain);
      continue;
    }
    if (/^(下一步|建议|建議|你可以|可继续|next step|next action|suggestion)/i.test(plain)) {
      sections.nextSteps.push(plain);
      continue;
    }
  }

  if (sections.understanding.length === 0 && lines.length > 0) {
    sections.understanding.push(lines[0]);
  }
  if (sections.filters.length === 0) {
    const compact = lines.join(" ");
    const gameMatch = compact.match(/《([^》]+)》/);
    if (gameMatch?.[1]) {
      sections.filters.push(`游戏：${gameMatch[1]}`);
    }
    if (/成人|NSFW/i.test(compact)) {
      sections.filters.push("内容分级：NSFW");
    } else if (/SFW|非成人/i.test(compact)) {
      sections.filters.push("内容分级：SFW");
    }
    if (/最近更新|latest|recent/i.test(compact)) {
      sections.filters.push("排序：updated_at_remote (降序)");
    }
  }
  if (sections.results.length === 0 && lines.length > 1) {
    sections.results.push(lines[1]);
  }
  if (sections.nextSteps.length === 0 && lines.length > 2) {
    sections.nextSteps.push(lines[lines.length - 1]);
  }

  return sections;
};

const AssistantResponseCard: React.FC<{
  text: string;
  matchesCount: number;
  matches?: AgentModMatch[];
  responseCards?: ChatMessage["responseCards"];
  onSelectNextStep?: (value: string) => void;
}> = ({ text, matchesCount, matches, responseCards, onSelectNextStep }) => {
  const { t } = useTranslation();
  const sections = responseCards
    ? {
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
    sections.understanding.length === 0 &&
    sections.filters.length === 0 &&
    sections.results.length === 0 &&
    sections.nextSteps.length === 0
  ) {
    return <MarkdownText text={text} className="text-sm" />;
  }

  const sectionClass = "rounded-xl border px-3 py-2";

  return (
    <div className="space-y-3 text-[14px]">
      <div className={`${sectionClass} border-sky-200 bg-sky-50/70`}>
        <p className="mb-1 text-[12px] font-semibold tracking-wide text-sky-700">{t("agent.section.understanding")}</p>
        <ul className="space-y-1 text-slate-800">
          {sections.understanding.map((line, idx) => (
            <li key={`understanding-${idx}`} className="leading-6">{line}</li>
          ))}
        </ul>
      </div>

      <div className={`${sectionClass} border-indigo-200 bg-indigo-50/60`}>
        <p className="mb-1 text-[12px] font-semibold tracking-wide text-indigo-700">{t("agent.section.filters")}</p>
        {sections.filters.length > 0 ? (
          <ul className="space-y-1 text-slate-800">
            {sections.filters.map((line, idx) => (
              <li key={`filters-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        ) : (
          <p className="text-slate-500">{t("agent.section.filtersEmpty")}</p>
        )}
      </div>

      <div className={`${sectionClass} border-emerald-200 bg-emerald-50/60`}>
        <p className="mb-1 text-[12px] font-semibold tracking-wide text-emerald-700">{t("agent.section.results")}</p>
        {sections.results.length > 0 ? (
          <ul className="space-y-1 text-slate-800">
            {sections.results.map((line, idx) => (
              <li key={`results-${idx}`} className="leading-6">{line}</li>
            ))}
          </ul>
        ) : (
          <p className="text-slate-800">{t("agent.section.resultsCount", { count: matchesCount })}</p>
        )}
      </div>

      <div className={`${sectionClass} border-amber-200 bg-amber-50/60`}>
        <p className="mb-1 text-[12px] font-semibold tracking-wide text-amber-700">{t("agent.section.nextSteps")}</p>
        {sections.nextSteps.length > 0 ? (
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
        ) : (
          <p className="text-slate-500">{t("agent.section.nextStepsHint")}</p>
        )}
      </div>
    </div>
  );
};

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
  const sourceClass =
    item.source?.toLowerCase() === "nexusmods"
      ? "border-indigo-200 bg-indigo-50 text-indigo-700"
      : "border-slate-200 bg-slate-100 text-slate-700";
  const safetyLabel = item.adult_content === true ? "NSFW" : item.adult_content === false ? "SFW" : "";
  const safetyClass =
    item.adult_content === true
      ? "border-rose-200 bg-rose-50 text-rose-700"
      : item.adult_content === false
        ? "border-emerald-200 bg-emerald-50 text-emerald-700"
        : "";

  return (
    <div className="rounded-xl border border-slate-200 bg-white p-3 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="text-[14px] font-semibold text-slate-900">{item.title}</div>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${sourceClass}`}>
          {item.source}
        </span>
        <span className="inline-flex items-center rounded-full border border-slate-200 bg-slate-50 px-2 py-0.5 text-[11px] text-slate-600">
          {item.game}
        </span>
        {item.adult_content !== null && item.adult_content !== undefined && (
          <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] ${safetyClass}`}>
            {safetyLabel}
          </span>
        )}
      </div>
      <div className="mt-1 text-[12px] text-slate-500">
        {item.author || "unknown"}
      </div>
      {hasSummary && (
        <div className="mt-2 space-y-1.5">
          <p
            className={`mt-0.5 whitespace-pre-wrap text-[13px] leading-6 text-slate-700 ${
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
          className="mt-2 inline-flex items-center gap-1 text-[12px] text-indigo-600 hover:text-indigo-700"
          title={expanded ? t("mod.collapseSummary") : t("mod.expandSummary")}
        >
          {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
          <span>{expanded ? t("mod.collapseSummary") : t("mod.expandSummary")}</span>
        </button>
      )}
      <div className="mt-2 flex items-center gap-3 text-[12px]">
        <button
          type="button"
          onClick={() => onToggleFavorite(item.id, isFavorited)}
          className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900"
          title={isFavorited ? t("mod.unfavorite") : t("mod.favorite")}
        >
          {isFavorited ? <HeartOff size={12} className="text-red-500" /> : <Heart size={12} className="text-gray-400" />}
          <span>{isFavorited ? t("mod.unfavorite") : t("mod.favorite")}</span>
        </button>
        <a
          href={item.url}
          target="_blank"
          rel="noreferrer"
          className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-700"
          title={t("mod.openOriginal")}
        >
          <span>{t("mod.openOriginal")}</span>
        </a>
        <button
          type="button"
          onClick={() => onAskDetail(item)}
          className="inline-flex items-center gap-1 text-indigo-600 hover:text-indigo-700"
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
  const activeSessionIdRef = useRef("");
  const [copiedId, setCopiedId] = useState<string>("");
  const [selectedModelKey, setSelectedModelKey] = useState("");
  const [selectedSource, setSelectedSource] = useState<"" | "nexusmods" | "loverslab">("");
  const [selectedGame, setSelectedGame] = useState("");
  const [selectedSortField, setSelectedSortField] = useState<
    "" | "updated_at_remote" | "downloads" | "endorsements" | "likes" | "relevance"
  >("");
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const loadedRef = useRef(false);
  const saveTimerRef = useRef<number | null>(null);
  const savingRef = useRef(false);
  const pendingSaveRef = useRef<{ data: ChatMessage[]; sessionId: string; clientUpdatedAt: string } | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

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
  const settingsQuery = useQuery({
    queryKey: ["settings", "agent-models"],
    queryFn: fetchSettings,
    staleTime: 60_000,
  });
  const gamesQuery = useQuery({
    queryKey: ["mod-games", "agent-chat"],
    queryFn: fetchModGames,
    staleTime: 60_000,
  });

  const providerDisplays = useMemo<AgentProviderDisplay[]>(() => {
    const settings = settingsQuery.data;
    if (!settings) return [];
    const options: AgentProviderDisplay[] = [];
    const seen = new Set<string>();
    const enabled = [...(settings.llmProviders || [])]
      .filter((item) => item.enabled)
      .sort((a, b) => a.priority - b.priority);
    for (const item of enabled) {
      const provider = item.provider;
      const model = item.model.trim();
      if (!provider) continue;
      const key = `${provider}::${model || "default"}`;
      if (seen.has(key)) continue;
      seen.add(key);
      options.push({
        key,
        provider,
        model,
        label: model ? `${provider} / ${model}` : provider,
      });
    }
    if (options.length === 0 && settings.llmProvider && settings.llmModel) {
      const provider = settings.llmProvider;
      const model = settings.llmModel.trim();
      if (model) {
        options.push({
          key: `${provider}::${model}`,
          provider,
          model,
          label: `${provider} / ${model}`,
        });
      }
    }
    return options;
  }, [settingsQuery.data]);

  const selectedModelOption = useMemo(
    () => providerDisplays.find((item) => item.key === selectedModelKey) || providerDisplays[0],
    [providerDisplays, selectedModelKey],
  );

  useEffect(() => {
    activeSessionIdRef.current = activeSessionId;
  }, [activeSessionId]);

  const visibleMessages = useMemo(
    () => messages.filter((message) => message.sessionId === activeSessionId || message.role === "separator"),
    [activeSessionId, messages],
  );

  useEffect(() => {
    if (!activeSessionId || providerDisplays.length === 0) return;
    const storageKey = `agent:selected-model:${activeSessionId}`;
    const stored = window.sessionStorage.getItem(storageKey) || "";
    const nextKey = providerDisplays.some((item) => item.key === stored) ? stored : providerDisplays[0].key;
    setSelectedModelKey((current) => {
      if (current && providerDisplays.some((item) => item.key === current)) return current;
      return nextKey;
    });
  }, [activeSessionId, providerDisplays]);

  const updateSelectedModel = (key: string) => {
    setSelectedModelKey(key);
    if (activeSessionId) {
      window.sessionStorage.setItem(`agent:selected-model:${activeSessionId}`, key);
    }
  };

  const createWelcomeMessage = (sessionId: string, id = "welcome"): ChatMessage => ({
    id,
    role: "assistant",
    text: t("agent.hint"),
    sessionId,
  });

  useEffect(() => {
    if (loadedRef.current || conversationQuery.isLoading) return;
    loadedRef.current = true;
    const state = conversationQuery.data;
    if (state && state.messages.length > 0) {
      const activeConversationId = state.active_session_id || state.messages[state.messages.length - 1]?.session_id || `sess_${Date.now()}`;
      const currentMessages = state.messages
        .map((m) => ({
          id: m.id,
          role: m.role,
          text: m.text,
          sessionId: m.session_id,
          createdAt: m.created_at,
          matches: m.matches,
          responseCards: m.response_cards
            ? {
                understanding: m.response_cards.understanding,
                filters: m.response_cards.filters,
                results: m.response_cards.results,
                nextSteps: m.response_cards.next_steps,
              }
            : undefined,
          llmProvider: m.llm_provider,
          llmModel: m.llm_model,
        }))
        .filter((m) => m.sessionId === activeConversationId && m.role !== "separator");
      const firstWelcomeIndex = currentMessages.findIndex((m) => m.role === "assistant" && m.text === t("agent.hint"));
      const dedupedMessages = currentMessages.filter(
        (m, index) => !(m.role === "assistant" && m.text === t("agent.hint") && index !== firstWelcomeIndex),
      );
      setActiveSessionId(activeConversationId);
      setMessages(dedupedMessages.length > 0 ? dedupedMessages : [createWelcomeMessage(activeConversationId)]);
      return;
    }
    const initialSessionId = state?.active_session_id || `sess_${Date.now()}`;
    setActiveSessionId(initialSessionId);
    setMessages([createWelcomeMessage(initialSessionId)]);
  }, [conversationQuery.data, conversationQuery.isLoading, t]);

  const saveConversationMutation = useMutation({
    mutationFn: ({ data, sessionId, clientUpdatedAt }: { data: ChatMessage[]; sessionId: string; clientUpdatedAt: string }) => {
      const payload: AgentConversationMessage[] = data.slice(-300).map((m) => ({
        id: m.id,
        role: m.role,
        text: m.text,
        session_id: m.sessionId,
        created_at: m.createdAt,
        matches: m.matches,
        response_cards: m.responseCards
          ? {
              understanding: m.responseCards.understanding,
              filters: m.responseCards.filters,
              results: m.responseCards.results,
              next_steps: m.responseCards.nextSteps,
            }
          : undefined,
        llm_provider: m.llmProvider,
        llm_model: m.llmModel,
      }));
      return saveAgentConversationState(payload, sessionId, clientUpdatedAt);
    },
  });

  const clearConversationMutation = useMutation({
    mutationFn: ({ sessionId, clientUpdatedAt }: { sessionId: string; clientUpdatedAt: string }) =>
      saveAgentConversationState([], sessionId, clientUpdatedAt),
  });

  const flushPendingSave = () => {
    if (savingRef.current) return;
    const snapshot = pendingSaveRef.current;
    if (!snapshot) return;
    pendingSaveRef.current = null;
    savingRef.current = true;
    saveConversationMutation.mutate(snapshot, {
      onSuccess: () => {
        savingRef.current = false;
        if (pendingSaveRef.current) {
          flushPendingSave();
        }
      },
      onError: () => {
        savingRef.current = false;
        if (!pendingSaveRef.current) {
          pendingSaveRef.current = {
            data: snapshot.data,
            sessionId: snapshot.sessionId,
            clientUpdatedAt: new Date().toISOString(),
          };
        }
        window.setTimeout(() => {
          flushPendingSave();
        }, 1000);
      },
    });
  };

  useEffect(() => {
    if (!loadedRef.current || !activeSessionId) return;
    const activeMessages = messages.filter((message) => message.sessionId === activeSessionId);
    pendingSaveRef.current = {
      data: activeMessages,
      sessionId: activeSessionId,
      clientUpdatedAt: new Date().toISOString(),
    };
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

  const buildHistory = (list: ChatMessage[], sessionId: string): AgentHistoryItem[] =>
    list
      .filter(
        (m): m is ChatMessage & { role: "user" | "assistant" } =>
          (m.role === "user" || m.role === "assistant") && m.sessionId === sessionId,
      )
      .map((m) => ({ role: m.role, text: m.text }))
      .slice(-40);

  const answerModelLabel = (msg: ChatMessage) => {
    if (msg.role !== "assistant" || !msg.llmModel) return "";
    return msg.llmProvider ? `${msg.llmProvider} / ${msg.llmModel}` : msg.llmModel;
  };

  const buildScopedMessage = (rawMessage: string): string => {
    const constraints: string[] = [];
    if (selectedSource) {
      constraints.push(`source=${selectedSource}`);
    }
    if (selectedGame) {
      constraints.push(`game=${selectedGame}`);
    }
    if (selectedSortField) {
      constraints.push(`sort_field=${selectedSortField}`);
    }
    if (constraints.length === 0) {
      return rawMessage;
    }
    return `${rawMessage}\n\n[scope]\n${constraints.join("\n")}`;
  };

  const mutation = useMutation({
    mutationFn: ({
      message,
      history,
      providerOverride,
      modelOverride,
    }: {
      message: string;
      history: AgentHistoryItem[];
      sessionId: string;
      providerOverride?: string;
      modelOverride?: string;
    }) =>
      chatWithAgent(message, history, {
        providerOverride,
        modelOverride,
      }),
    onSuccess: (data, variables) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant`,
          role: "assistant",
          text: data.answer,
          sessionId: variables.sessionId,
          matches: data.matches,
          responseCards: data.response_cards
            ? {
                understanding: data.response_cards.understanding,
                filters: data.response_cards.filters,
                results: data.response_cards.results,
                nextSteps: data.response_cards.next_steps,
              }
            : undefined,
          llmProvider: data.llm_provider,
          llmModel: data.llm_model,
        },
      ]);
      if (activeSessionIdRef.current === variables.sessionId) {
        setTimeout(() => {
          viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: "smooth" });
        }, 30);
      }
    },
    onError: (error, variables) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant-error`,
          role: "assistant",
          text: (error as Error).message,
          sessionId: variables.sessionId,
        },
      ]);
    },
  });

  const onSubmit = () => {
    const message = input.trim();
    if (!message) return;
    const requestSessionId = activeSessionId || `sess_${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-user`, role: "user", text: message, sessionId: requestSessionId },
    ]);
    setInput("");
    mutation.mutate({
      message: buildScopedMessage(message),
      history: buildHistory(messages, requestSessionId),
      sessionId: requestSessionId,
      providerOverride: selectedModelOption?.provider,
      modelOverride: selectedModelOption?.model,
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
    mutationFn: ({
      modId,
      question,
      history,
      providerOverride,
      modelOverride,
    }: {
      modId: number;
      question?: string;
      history: AgentHistoryItem[];
      sessionId: string;
      providerOverride?: string;
      modelOverride?: string;
    }) =>
      askAgentModDetail(modId, question, history, {
        providerOverride,
        modelOverride,
      }),
    onSuccess: (data, variables) => {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant-detail`,
          role: "assistant",
          text: data.answer,
          sessionId: variables.sessionId,
          matches: data.matches,
          responseCards: data.response_cards
            ? {
                understanding: data.response_cards.understanding,
                filters: data.response_cards.filters,
                results: data.response_cards.results,
                nextSteps: data.response_cards.next_steps,
              }
            : undefined,
          llmProvider: data.llm_provider,
          llmModel: data.llm_model,
        },
      ]);
      if (activeSessionIdRef.current === variables.sessionId) {
        setTimeout(() => {
          viewportRef.current?.scrollTo({ top: viewportRef.current.scrollHeight, behavior: "smooth" });
        }, 30);
      }
    },
  });

  const currentSessionBusy =
    (mutation.isPending && mutation.variables?.sessionId === activeSessionId) ||
    (detailMutation.isPending && detailMutation.variables?.sessionId === activeSessionId);

  const selectNextStep = (value: string) => {
    setInput(value);
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const onAskDetail = (mod: AgentModMatch) => {
    const askText = `请详细解析这个 Mod：${mod.title}`;
    const requestSessionId = activeSessionId || `sess_${Date.now()}`;
    setMessages((prev) => [
      ...prev,
      { id: `${Date.now()}-user-detail`, role: "user", text: askText, sessionId: requestSessionId },
    ]);
    detailMutation.mutate({
      modId: mod.id,
      question: askText,
      history: buildHistory(messages, requestSessionId),
      sessionId: requestSessionId,
      providerOverride: selectedModelOption?.provider,
      modelOverride: selectedModelOption?.model,
    });
  };

  const copyMessage = async (id: string, text: string) => {
    const value = text.trim();
    if (!value) return;
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value);
      } else {
        const textarea = document.createElement("textarea");
        textarea.value = value;
        textarea.setAttribute("readonly", "true");
        textarea.style.position = "fixed";
        textarea.style.left = "-9999px";
        textarea.style.top = "0";
        document.body.appendChild(textarea);
        textarea.focus();
        textarea.select();
        const copied = document.execCommand("copy");
        document.body.removeChild(textarea);
        if (!copied) {
          throw new Error("copy failed");
        }
      }
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
    setMessages([createWelcomeMessage(nextSessionId, `${Date.now()}-welcome`)]);
  };

  const handleConfirmClearScreen = async () => {
    const currentSessionId = activeSessionId || `sess_${Date.now()}`;
    const nextMessages: ChatMessage[] = [
      createWelcomeMessage(currentSessionId, `${Date.now()}-assistant-cleared`),
    ];
    try {
      if (saveTimerRef.current) {
        window.clearTimeout(saveTimerRef.current);
        saveTimerRef.current = null;
      }
      pendingSaveRef.current = null;
      await clearConversationMutation.mutateAsync({
        sessionId: currentSessionId,
        clientUpdatedAt: new Date().toISOString(),
      });
      setMessages(nextMessages);
      setClearConfirmOpen(false);
      setTimeout(() => {
        viewportRef.current?.scrollTo({ top: 0, behavior: "smooth" });
      }, 20);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: `${Date.now()}-assistant-clear-error`,
          role: "assistant",
          text: (error as Error).message || t("agent.clearFailed"),
          sessionId: currentSessionId,
        },
      ]);
      setClearConfirmOpen(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <div className="flex h-screen">
        <AppSidebar active="agent" />

        <main className="flex-1 flex flex-col min-h-0">
          <div className="px-6 py-5 lg:px-8">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <h1 className="text-3xl font-bold tracking-normal text-slate-950">{t("agent.title")}</h1>
                  <Sparkles size={24} className="text-blue-600" />
                </div>
                <p className="mt-2 text-sm font-semibold text-slate-500">{t("agent.subtitle")}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setClearConfirmOpen(true)}
                  className="inline-flex h-11 items-center gap-2 rounded-lg border border-red-200 bg-white px-4 text-sm font-bold text-red-500 transition hover:bg-red-50"
                >
                  <Trash2 size={16} />
                  {t("agent.clearScreen")}
                </button>
                <button
                  type="button"
                  onClick={handleStartNewConversation}
                  className="inline-flex h-11 items-center gap-2 rounded-lg border border-blue-200 bg-white px-4 text-sm font-bold text-blue-600 transition hover:bg-blue-50"
                >
                  <Plus size={17} />
                  {t("agent.startNewConversation")}
                </button>
              </div>
            </div>
          </div>

          <div ref={viewportRef} className="flex-1 overflow-y-auto px-6 pb-6 lg:px-8">
            <div className="mx-auto max-w-6xl space-y-5">
              {visibleMessages.map((msg) => (
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
                <div className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"} ${msg.role === "assistant" ? "gap-4" : ""}`}>
                  {msg.role === "assistant" && (
                    <div className="mt-1 hidden h-12 w-12 shrink-0 items-center justify-center rounded-full border border-blue-100 bg-white text-blue-600 shadow-sm md:flex">
                      <Sparkles size={22} />
                    </div>
                  )}
                  <div
                    className={`${
                      msg.role === "user"
                        ? "w-full max-w-[620px] min-w-0 sm:min-w-[460px]"
                        : "w-full max-w-[980px]"
                    } ${msg.role === "assistant" ? "space-y-1" : ""}`}
                  >
                    {answerModelLabel(msg) && (
                      <div className="pl-2 text-[11px] leading-4 text-slate-400">
                        {answerModelLabel(msg)}
                      </div>
                    )}
                    <div
                      className={`rounded-2xl border px-4 py-3 shadow-[0_10px_28px_rgba(15,23,42,0.06)] ${
                      msg.role === "user"
                        ? "border-blue-500 bg-blue-600 text-white"
                        : "border-slate-200 bg-white text-slate-900"
                     }`}
                     >
                    {msg.role === "assistant" ? (
                      <AssistantResponseCard
                        text={msg.text}
                        matchesCount={msg.matches?.length || 0}
                        matches={msg.matches}
                        responseCards={msg.responseCards}
                        onSelectNextStep={selectNextStep}
                      />
                    ) : (
                      <div className="whitespace-pre-wrap text-[14px]">{msg.text}</div>
                    )}
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
                      className={`mt-2 inline-flex items-center gap-1 text-[12px] ${
                        msg.role === "user" ? "text-indigo-100 hover:text-white" : "text-slate-500 hover:text-slate-700"
                      }`}
                    >
                      {copiedId === msg.id ? <Check size={12} /> : <Copy size={12} />}
                      {copiedId === msg.id ? t("agent.copied") : t("agent.copy")}
                    </button>
                    </div>
                  </div>
                </div>
                  )}
                </div>
              ))}
              {currentSessionBusy && (
                <div className="flex justify-start">
                  <div className="inline-flex items-center gap-2 rounded-2xl border border-slate-200 bg-white px-4 py-3 text-[14px] text-slate-500">
                    <Loader2 size={14} className="animate-spin" />
                    {t("common.loading")}
                  </div>
                </div>
              )}
            </div>
          </div>

          <div className="bg-slate-50 px-6 pb-5 lg:px-8">
            <div className="mx-auto max-w-6xl rounded-2xl border border-blue-200 bg-white p-4 shadow-[0_12px_32px_rgba(37,99,235,0.08)]">
              <div className="mb-3 flex flex-wrap items-center gap-2 text-sm font-semibold text-slate-500">
                <span>{t("agent.quickPromptLabel")}</span>
                {[t("agent.quickPrompt.male"), t("agent.quickPrompt.recent"), t("agent.quickPrompt.downloads"), t("agent.quickPrompt.outfits")].map((prompt) => (
                  <button
                    key={prompt}
                    type="button"
                    onClick={() => setInput(prompt)}
                    className="rounded-full border border-slate-200 bg-white px-3 py-1.5 text-slate-600 transition hover:border-blue-200 hover:bg-blue-50 hover:text-blue-700"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
              <div className="flex gap-3">
                <input
                  ref={inputRef}
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") onSubmit();
                  }}
                  placeholder={t("agent.placeholder")}
                  className="h-12 flex-1 rounded-xl border border-slate-300 px-4 text-[15px] text-slate-900 shadow-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
                />
                <Button onClick={onSubmit} disabled={mutation.isPending || detailMutation.isPending} className="h-12 w-14 rounded-xl shadow-sm">
                  <Send size={20} />
                </Button>
              </div>
              <div className="mt-3">
                <div className="grid w-full grid-cols-1 gap-3 text-sm text-slate-500 md:grid-cols-2 xl:grid-cols-4">
                  <label className="space-y-1.5">
                    <span className="font-semibold">{t("agent.model")}</span>
                    <select
                      value={selectedModelOption?.key || ""}
                      onChange={(e) => updateSelectedModel(e.target.value)}
                      className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-700"
                      disabled={providerDisplays.length === 0 || mutation.isPending || detailMutation.isPending}
                    >
                      {providerDisplays.map((item) => (
                        <option key={item.key} value={item.key}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                    {providerDisplays.length === 0 && (
                      <span className="block text-xs text-slate-400">{t("agent.noLlmProviders")}</span>
                    )}
                  </label>

                  <label className="space-y-1.5">
                    <span className="font-semibold">{t("discover.source")}</span>
                    <select
                      value={selectedSource}
                      onChange={(e) => setSelectedSource(e.target.value as "" | "nexusmods" | "loverslab")}
                      className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-700"
                      disabled={mutation.isPending || detailMutation.isPending}
                    >
                      <option value="">{t("discover.allSources")}</option>
                      <option value="nexusmods">{t("discover.sourceNexusmods")}</option>
                      <option value="loverslab">{t("discover.sourceLoverslab")}</option>
                    </select>
                  </label>

                  <label className="space-y-1.5">
                    <span className="font-semibold">{t("discover.game")}</span>
                    <select
                      value={selectedGame}
                      onChange={(e) => setSelectedGame(e.target.value)}
                      className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-700"
                      disabled={mutation.isPending || detailMutation.isPending}
                    >
                      <option value="">{t("discover.allGames")}</option>
                      {(gamesQuery.data || []).map((item) => (
                        <option key={item.value} value={item.value}>
                          {item.label}
                        </option>
                      ))}
                    </select>
                  </label>

                  <label className="space-y-1.5">
                    <span className="font-semibold">{t("agent.sortField")}</span>
                    <select
                      value={selectedSortField}
                      onChange={(e) =>
                        setSelectedSortField(
                          e.target.value as "" | "updated_at_remote" | "downloads" | "endorsements" | "likes" | "relevance",
                        )
                      }
                      className="h-10 w-full rounded-lg border border-slate-300 bg-white px-3 text-sm text-slate-700"
                      disabled={mutation.isPending || detailMutation.isPending}
                    >
                      <option value="">{t("agent.sortAuto")}</option>
                      <option value="updated_at_remote">{t("agent.sortUpdatedAt")}</option>
                      <option value="downloads">{t("mod.downloads")}</option>
                      <option value="endorsements">{t("mod.endorsements")}</option>
                      <option value="likes">{t("mod.likes")}</option>
                      <option value="relevance">{t("agent.sortRelevance")}</option>
                    </select>
                  </label>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
      {clearConfirmOpen && (
        <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/20 p-4">
          <div className="relative w-full max-w-sm rounded-2xl border border-slate-200 bg-white p-6 text-center shadow-2xl">
            <button
              type="button"
              onClick={() => setClearConfirmOpen(false)}
              className="absolute right-4 top-4 rounded-full p-1 text-slate-400 hover:bg-slate-50 hover:text-slate-700"
              aria-label={t("common.close")}
            >
              <X size={18} />
            </button>
            <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border border-blue-100 bg-blue-50 text-blue-600">
              <Trash2 size={34} />
            </div>
            <h3 className="mt-5 text-xl font-bold text-slate-950">{t("agent.clearConfirmTitle")}</h3>
            <p className="mt-3 text-sm font-semibold leading-6 text-slate-500">{t("agent.clearConfirmBody")}</p>
            <div className="mt-6 grid grid-cols-2 gap-3">
              <button
                type="button"
                onClick={() => setClearConfirmOpen(false)}
                className="h-11 rounded-lg border border-slate-300 px-3 text-sm font-bold text-slate-700 hover:bg-slate-50"
              >
                {t("agent.clearConfirmCancel")}
              </button>
              <button
                type="button"
                onClick={handleConfirmClearScreen}
                className="h-11 rounded-lg bg-red-500 px-3 text-sm font-bold text-white hover:bg-red-600"
              >
                {t("agent.clearConfirmAction")}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default AgentChat;
