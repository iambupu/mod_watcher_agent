import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useMutation, useQuery } from "@tanstack/react-query";
import {
  Send,
  Loader2,
  Copy,
  Check,
  Sparkles,
  Plus,
  Trash2,
} from "lucide-react";
import { Button } from "@/components/ui/Button";
import { FilterSelect } from "@/components/ui/FilterControls";
import { ConfirmModal } from "@/components/ui/ConfirmModal";
import {
  askAgentModDetail,
  chatWithAgent,
  fetchAgentConversationState,
  startAgentConversation,
  type AgentHistoryItem,
  type AgentModMatch,
} from "@/api/agent";
import { addFavorite, favoriteIdByModId, fetchFavoriteRefs, removeFavorite } from "@/api/favorites";
import { fetchModGames } from "@/api/mods";
import AppSidebar from "@/components/layout/AppSidebar";
import { AgentMatchCard } from "@/features/agentChat/AgentMatchCard";
import { AssistantResponseCard } from "@/features/agentChat/AssistantResponseCard";
import {
  conflictFieldQuestion,
  normalizeSourceCandidate,
  reviewTargetQuestion,
  scopeFieldQuestion,
  sourceCandidateQuestion,
  toChatResponseCards,
} from "@/features/agentChat/responseCards";
import type { AgentProviderDisplay, ChatMessage } from "@/features/agentChat/types";
import { useAgentConversationPersistence } from "@/features/agentChat/useAgentConversationPersistence";
import { fetchSettings } from "@/api/settings";

const AgentChat: React.FC = () => {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [activeSessionId, setActiveSessionId] = useState("");
  const [copiedId, setCopiedId] = useState<string>("");
  const [selectedModelKey, setSelectedModelKey] = useState("");
  const [selectedSource, setSelectedSource] = useState<"" | "nexusmods" | "loverslab">("");
  const [selectedGame, setSelectedGame] = useState("");
  const [selectedSortField, setSelectedSortField] = useState<
    "" | "updated_at_remote" | "downloads" | "endorsements" | "likes" | "relevance"
  >("");
  const [clearConfirmOpen, setClearConfirmOpen] = useState(false);
  const viewportRef = useRef<HTMLDivElement>(null);
  const copiedTimerRef = useRef<number | null>(null);
  const scrollTimerRef = useRef<number | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const favoritesQuery = useQuery({
    queryKey: ["favorites", "refs"],
    queryFn: fetchFavoriteRefs,
    staleTime: 30_000,
  });
  const favoriteByModId = useMemo(() => {
    const map = favoriteIdByModId(favoritesQuery.data);
    return map instanceof Map ? map : new Map<number, number>();
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

  const {
    activeSessionIdRef,
    createWelcomeMessage,
    queueActiveSessionSave,
    flushPendingSave,
    clearConversation,
    clearConversationPending,
  } = useAgentConversationPersistence({
    messages,
    setMessages,
    activeSessionId,
    setActiveSessionId,
    conversationState: conversationQuery.data,
    conversationStateLoading: conversationQuery.isLoading,
    refetchConversationState: conversationQuery.refetch,
    welcomeText: t("agent.hint"),
  });

  const providerDisplays = useMemo<AgentProviderDisplay[]>(() => {
    const settings = settingsQuery.data;
    if (!settings) return [];
    const options: AgentProviderDisplay[] = [];
    const seen = new Set<string>();
    // 设置页允许多个供应商；这里按优先级生成会话级可选模型，并去掉重复配置。
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

  const visibleMessages = useMemo(
    () => messages.filter((message) => message.sessionId === activeSessionId || message.role === "separator"),
    [activeSessionId, messages],
  );

  useEffect(() => {
    if (!activeSessionId || providerDisplays.length === 0) return;
    const storageKey = `agent:selected-model:${activeSessionId}`;
    const stored = window.sessionStorage.getItem(storageKey) || "";
    // 模型选择只在当前浏览器 session 内记忆，避免影响服务端保存的对话内容。
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

  const scheduleViewportScroll = (top: "bottom" | number, delayMs = 30) => {
    if (scrollTimerRef.current) {
      window.clearTimeout(scrollTimerRef.current);
    }
    scrollTimerRef.current = window.setTimeout(() => {
      scrollTimerRef.current = null;
      const viewport = viewportRef.current;
      if (!viewport) return;
      viewport.scrollTo({
        top: top === "bottom" ? viewport.scrollHeight : top,
        behavior: "smooth",
      });
    }, delayMs);
  };

  useEffect(() => {
    return () => {
      if (copiedTimerRef.current) {
        window.clearTimeout(copiedTimerRef.current);
      }
      if (scrollTimerRef.current) {
        window.clearTimeout(scrollTimerRef.current);
      }
    };
  }, []);

  const buildHistoryText = (message: ChatMessage): string => {
    if (message.role !== "assistant" || !message.matches?.length) {
      return message.text;
    }
    // 把已展示候选压缩进历史，后端才能理解“第二个”“类似这个”等追问。
    const shownMods = message.matches.slice(0, 12).map((item, index) =>
      `${index + 1}. title=${item.title}; source=${item.source}; game=${item.game}; category=${item.category || ""}`,
    );
    return `${message.text}\n\n[shown_mods]\n${shownMods.join("\n")}`.slice(0, 4000);
  };

  const buildHistory = (list: ChatMessage[], sessionId: string): AgentHistoryItem[] =>
    list
      .filter(
        (m): m is ChatMessage & { role: "user" | "assistant" } =>
          (m.role === "user" || m.role === "assistant") && m.sessionId === sessionId,
      )
      .map((m) => ({ role: m.role, text: buildHistoryText(m) }))
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
    // [scope] 是前后端约定的硬约束块；后端会把它从自然语言关键词中剥离。
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
          responseCards: toChatResponseCards(data.response_cards),
          llmProvider: data.llm_provider,
          llmModel: data.llm_model,
          audit: data.audit,
        },
      ]);
      if (activeSessionIdRef.current === variables.sessionId) {
        scheduleViewportScroll("bottom");
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
    // 先乐观插入用户消息，提交给后端的 history 使用插入前快照，避免当前消息重复出现。
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
    scheduleViewportScroll("bottom");
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
          responseCards: toChatResponseCards(data.response_cards),
          llmProvider: data.llm_provider,
          llmModel: data.llm_model,
          audit: data.audit,
        },
      ]);
      if (activeSessionIdRef.current === variables.sessionId) {
        scheduleViewportScroll("bottom");
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

  const applySourceCandidate = (candidate: string) => {
    const source = normalizeSourceCandidate(candidate);
    if (source === "nexusmods" || source === "loverslab") {
      // 来源候选按钮同时更新筛选器和输入框，使下一次请求携带显式 scope。
      setSelectedSource(source);
      setInput((prev) => (prev.trim() ? prev : sourceCandidateQuestion(source)));
      window.requestAnimationFrame(() => inputRef.current?.focus());
    }
  };

  const applyScopeField = (field: string) => {
    const key = field.trim().toLowerCase();
    const template =
      key === "game"
        ? "我想限定目标游戏为 "
        : key === "source"
          ? "我想优先查 "
          : key === "keywords"
            ? "我想补充关键词："
            : key === "category" || key === "categories"
              ? "我想按这个类型或风格继续查："
              : `${scopeFieldQuestion(field)}：`;
    setInput((prev) => (prev.trim() ? prev : template));
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const applyReviewTarget = (target: string) => {
    const key = target.trim().toLowerCase();
    const template =
      key === "memory_signals"
        ? "请解释你参考了哪些记忆信号。"
        : key === "context_slots"
          ? "请解释你继承了哪些上下文条件。"
          : key === "analysis_evidence"
            ? "请说明你理解这个需求的依据。"
            : `${reviewTargetQuestion(target)}。`;
    setInput((prev) => (prev.trim() ? prev : template));
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const applyConflictField = (field: string) => {
    const template = conflictFieldQuestion(field);
    setInput((prev) => (prev.trim() ? prev : template));
    window.requestAnimationFrame(() => inputRef.current?.focus());
  };

  const onAskDetail = (mod: AgentModMatch) => {
    const askText = `请详细解析这个 Mod：${mod.title}`;
    const requestSessionId = activeSessionId || `sess_${Date.now()}`;
    // 详情追问走独立接口，但仍携带当前会话历史，让后端保留上下文引用。
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
        // 兼容没有 Clipboard API 的 WebView/旧浏览器环境。
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
      if (copiedTimerRef.current) {
        window.clearTimeout(copiedTimerRef.current);
      }
      copiedTimerRef.current = window.setTimeout(() => {
        copiedTimerRef.current = null;
        setCopiedId("");
      }, 1000);
    } catch {
      setCopiedId("");
    }
  };

  const handleStartNewConversation = async () => {
    // 新会话前主动刷写当前 session，减少切换时最后一条消息丢失的概率。
    queueActiveSessionSave();
    flushPendingSave();
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
      await clearConversation(currentSessionId);
      setMessages(nextMessages);
      setClearConfirmOpen(false);
      scheduleViewportScroll(0, 20);
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
                        matches={msg.matches}
                        responseCards={msg.responseCards}
                        onSelectNextStep={selectNextStep}
                        expandOnlineCandidates={
                          msg.audit?.conclusion?.recommended_action === "expand_online_sources_and_narrow_scope"
                            ? msg.audit?.conclusion?.expand_online_candidates || []
                            : []
                        }
                        expandOnlineCandidateDetails={
                          msg.audit?.conclusion?.recommended_action === "expand_online_sources_and_narrow_scope"
                            ? msg.audit?.conclusion?.action_payload?.expand_online_candidates ||
                              msg.audit?.conclusion?.expand_online_candidates_detail ||
                              []
                            : []
                        }
                        narrowScopeFields={
                          msg.audit?.conclusion?.action_payload?.narrow_scope_fields || []
                        }
                        reviewTargets={msg.audit?.conclusion?.action_payload?.review_targets || []}
                        conflictFields={msg.audit?.conclusion?.action_payload?.conflict_fields || []}
                        onApplyScopeField={applyScopeField}
                        onApplyReviewTarget={applyReviewTarget}
                        onApplyConflictField={applyConflictField}
                        onApplySourceCandidate={applySourceCandidate}
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
                  <FilterSelect
                    label={t("agent.model")}
                    labelClassName="font-semibold text-slate-500"
                    value={selectedModelOption?.key || ""}
                    onValueChange={updateSelectedModel}
                    controlSize="sm"
                    disabled={providerDisplays.length === 0 || mutation.isPending || detailMutation.isPending}
                    className="h-10 w-full"
                  >
                    {providerDisplays.map((item) => (
                      <option key={item.key} value={item.key}>
                        {item.label}
                      </option>
                    ))}
                  </FilterSelect>
                  {providerDisplays.length === 0 && (
                    <span className="block text-xs text-slate-400">{t("agent.noLlmProviders")}</span>
                  )}

                  <FilterSelect
                    label={t("discover.source")}
                    labelClassName="font-semibold text-slate-500"
                    value={selectedSource}
                    onValueChange={(value) => setSelectedSource(value as "" | "nexusmods" | "loverslab")}
                    controlSize="sm"
                    disabled={mutation.isPending || detailMutation.isPending}
                    className="h-10 w-full"
                  >
                    <option value="">{t("discover.allSources")}</option>
                    <option value="nexusmods">{t("discover.sourceNexusmods")}</option>
                    <option value="loverslab">{t("discover.sourceLoverslab")}</option>
                  </FilterSelect>

                  <FilterSelect
                    label={t("discover.game")}
                    labelClassName="font-semibold text-slate-500"
                    value={selectedGame}
                    onValueChange={setSelectedGame}
                    controlSize="sm"
                    disabled={mutation.isPending || detailMutation.isPending}
                    className="h-10 w-full"
                  >
                    <option value="">{t("discover.allGames")}</option>
                    {(gamesQuery.data || []).map((item) => (
                      <option key={item.value} value={item.value}>
                        {item.label}
                      </option>
                    ))}
                  </FilterSelect>

                  <FilterSelect
                    label={t("agent.sortField")}
                    labelClassName="font-semibold text-slate-500"
                    value={selectedSortField}
                    onValueChange={(value) =>
                      setSelectedSortField(
                        value as "" | "updated_at_remote" | "downloads" | "endorsements" | "likes" | "relevance",
                      )
                    }
                    controlSize="sm"
                    disabled={mutation.isPending || detailMutation.isPending}
                    className="h-10 w-full"
                  >
                    <option value="">{t("agent.sortAuto")}</option>
                    <option value="updated_at_remote">{t("agent.sortUpdatedAt")}</option>
                    <option value="downloads">{t("mod.downloads")}</option>
                    <option value="endorsements">{t("mod.endorsements")}</option>
                    <option value="likes">{t("mod.likes")}</option>
                    <option value="relevance">{t("agent.sortRelevance")}</option>
                  </FilterSelect>
                </div>
              </div>
            </div>
          </div>
        </main>
      </div>
      {clearConfirmOpen && (
        <ConfirmModal
          open={clearConfirmOpen}
          onClose={() => setClearConfirmOpen(false)}
          onCancel={() => setClearConfirmOpen(false)}
          onConfirm={handleConfirmClearScreen}
          title={<span className="text-xl font-bold text-slate-950">{t("agent.clearConfirmTitle")}</span>}
          subtitle={<span className="text-sm font-semibold text-slate-500">{t("agent.clearConfirmBody")}</span>}
          closeAriaLabel={t("common.close")}
          closeOnBackdrop
          closeOnEscape
          panelClassName="w-full max-w-sm rounded-2xl bg-white p-6 text-center shadow-2xl"
          headerClassName="mb-3"
          messageClassName="mt-6"
          actionsClassName="mt-6 grid grid-cols-2 gap-3"
          confirmText={t("agent.clearConfirmAction")}
          cancelText={t("agent.clearConfirmCancel")}
          confirmClassName="h-11 rounded-lg bg-red-500 px-3 text-sm font-bold text-white hover:bg-red-600"
          cancelClassName="h-11 rounded-lg border border-slate-300 px-3 text-sm font-bold text-slate-700 hover:bg-slate-50"
          confirmVariant="default"
          cancelVariant="outline"
          confirmChildren={
            <>
              {clearConversationPending ? (
                <Loader2 size={16} className="mr-1.5 animate-spin" />
              ) : (
                t("agent.clearConfirmAction")
              )}
            </>
          }
        >
          <div className="mx-auto flex h-20 w-20 items-center justify-center rounded-full border border-blue-100 bg-blue-50 text-blue-600">
            <Trash2 size={34} />
          </div>
        </ConfirmModal>
      )}
    </div>
  );
};

export default AgentChat;
