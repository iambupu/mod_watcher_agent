import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";

import AgentChat from "@/pages/AgentChat";
import * as agentApi from "@/api/agent";
import * as favoritesApi from "@/api/favorites";
import * as modsApi from "@/api/mods";
import * as settingsApi from "@/api/settings";

vi.mock("@/api/agent");
vi.mock("@/api/favorites");
vi.mock("@/api/mods");
vi.mock("@/api/settings");
vi.mock("@/components/layout/AppSidebar", () => ({
  default: () => null,
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

describe("AgentChat expand online candidates", () => {
  let queryClient: QueryClient;

  beforeEach(() => {
    queryClient = new QueryClient({
      defaultOptions: {
        queries: { retry: false },
        mutations: { retry: false },
      },
    });
    vi.clearAllMocks();

    vi.mocked(favoritesApi.fetchFavorites).mockResolvedValue([]);
    vi.mocked(modsApi.fetchModGames).mockResolvedValue([]);
    vi.mocked(settingsApi.fetchSettings).mockResolvedValue({
      llmProviders: [],
      llmProvider: "openai",
      llmModel: "gpt-4o-mini",
    } as never);
    vi.mocked(agentApi.fetchAgentConversationState).mockResolvedValue({
      messages: [],
      active_session_id: "sess_test",
    });
    vi.mocked(agentApi.saveAgentConversationState).mockResolvedValue({
      messages: [],
      active_session_id: "sess_test",
    });
    vi.mocked(agentApi.startAgentConversation).mockResolvedValue({ session_id: "sess_test_2" });
    vi.mocked(agentApi.askAgentModDetail).mockResolvedValue({
      answer: "detail",
      used_llm: false,
      matches: [],
    });
    Element.prototype.scrollTo = vi.fn();
  });

  afterEach(() => {
    queryClient.clear();
  });

  function renderPage() {
    return render(
      <QueryClientProvider client={queryClient}>
        <MemoryRouter future={{ v7_relativeSplatPath: true, v7_startTransition: true }}>
          <AgentChat />
        </MemoryRouter>
      </QueryClientProvider>,
    );
  }

  it("renders candidate button and applies source shortcut on click", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        understanding: ["u"],
        filters: [],
        results: [],
        next_steps: ["n1"],
      },
      audit: {
        conclusion: {
          recommended_action: "expand_online_sources_and_narrow_scope",
          expand_online_candidates: ["loverslab_google"],
        },
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    await screen.findByText("agent.hint");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const candidateButton = await screen.findByRole("button", { name: "继续查 LoversLab 来源的结果" });
    expect(candidateButton).toBeInTheDocument();

    fireEvent.click(candidateButton);

    const sourceSelect = screen.getByDisplayValue("discover.sourceLoverslab") as HTMLSelectElement;
    expect(sourceSelect.value).toBe("loverslab");
    expect((input as HTMLInputElement).value).toContain("LoversLab");
  });

  it("renders and persists standardized analysis evidence conclusion cards", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        analysis: ["任务分析：识别跟进查询。"],
        evidence: ["证据：上一轮包含 bimbo 语义锚点。"],
        conclusion: ["结论：继续查找相关风格 Mod。"],
        understanding: ["u"],
        filters: [],
        results: [],
        next_steps: ["n1"],
      },
      audit: { conclusion: {} },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    await screen.findByText("agent.hint");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("agent.section.analysis")).toBeInTheDocument();
    expect(screen.getByText("任务分析：识别跟进查询。")).toBeInTheDocument();
    expect(screen.getByText("证据：上一轮包含 bimbo 语义锚点。")).toBeInTheDocument();
    expect(screen.getByText("结论：继续查找相关风格 Mod。")).toBeInTheDocument();
    let assistantMessage: agentApi.AgentConversationMessage | undefined;
    await waitFor(() => {
      const calls = vi.mocked(agentApi.saveAgentConversationState).mock.calls;
      assistantMessage = calls
        .flatMap(([messages]) => messages as agentApi.AgentConversationMessage[])
        .filter((item) => item.role === "assistant")
        .find((message) => message?.response_cards?.analysis);
      expect(assistantMessage?.response_cards?.analysis).toEqual(["任务分析：识别跟进查询。"]);
    });
    expect(assistantMessage?.response_cards?.analysis).toEqual(["任务分析：识别跟进查询。"]);
    expect(assistantMessage?.response_cards?.evidence).toEqual(["证据：上一轮包含 bimbo 语义锚点。"]);
    expect(assistantMessage?.response_cards?.conclusion).toEqual(["结论：继续查找相关风格 Mod。"]);
  });

  it("renders summaries in assistant mod result cards", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "找到候选。",
      used_llm: false,
      matches: [
        {
          id: 101,
          title: "Bimbos of Skyrim LE/SE",
          source: "loverslab",
          game: "skyrimspecialedition",
          author: "author",
          version: "1.0",
          url: "https://example.test/mod",
          score: 100,
          original_summary: "Adds bimbofied NPCs, quests, and a transformation curse.",
          translated_summary: "加入 bimbo 化 NPC、任务和转化诅咒。",
        },
      ],
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "天际有什么扮演bimbo的MOD" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("Bimbos of Skyrim LE/SE")).toBeInTheDocument();
    expect(await screen.findByText(/加入 bimbo 化 NPC/)).toBeInTheDocument();
  });

  it("renders answer body together with structured response cards", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "这是该 Mod 的详细解析正文，包含玩法、前置和风险。",
      used_llm: true,
      matches: [],
      response_cards: {
        analysis: ["任务分析：详细解析指定 Mod。"],
        evidence: ["证据：已定位到 Mod。"],
        conclusion: ["结论：可以查看详情。"],
        results: ["已生成该 Mod 的详细解析。"],
        next_steps: [],
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "请详细解析这个 Mod：Bimbos of Skyrim - BimboLips 1.3.1" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("这是该 Mod 的详细解析正文，包含玩法、前置和风险。")).toBeInTheDocument();
    expect(await screen.findByText("任务分析：详细解析指定 Mod。")).toBeInTheDocument();
  });

  it("uses rank reason as card description when source summaries are missing", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "找到候选。",
      used_llm: false,
      matches: [
        {
          id: 102,
          title: "Bimbo Body Preset",
          source: "nexusmods",
          game: "skyrimspecialedition",
          author: "author",
          version: "1.0",
          url: "https://example.test/preset",
          score: 88,
          rank_reason: "名称和分类都命中 bimbo 角色扮演需求。",
        },
      ],
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "天际有什么扮演bimbo的MOD" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("Bimbo Body Preset")).toBeInTheDocument();
    expect(await screen.findByText("agent.matchReason")).toBeInTheDocument();
    expect(await screen.findByText("名称和分类都命中 bimbo 角色扮演需求。")).toBeInTheDocument();
  });

  it("does not render empty legacy sections for analysis evidence conclusion only cards", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        analysis: ["任务分析：识别查询。"],
        evidence: ["证据：语义锚点已命中。"],
        conclusion: ["结论：可以继续检索。"],
      },
      audit: {
        evidence: {
          web_search: {
            enabled: true,
            queried: true,
            tools: ["nexusmods_search"],
            tool_statuses: { nexusmods_search: "succeeded" },
            tool_result_counts: { nexusmods_search: 2 },
          },
        },
        conclusion: {},
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByText("任务分析：识别查询。")).toBeInTheDocument();
    expect(screen.getByText("证据：语义锚点已命中。")).toBeInTheDocument();
    expect(screen.getByText("结论：可以继续检索。")).toBeInTheDocument();
    expect(screen.queryAllByText("agent.section.understanding")).toHaveLength(1);
    expect(screen.queryByText("agent.section.filters")).not.toBeInTheDocument();
    expect(screen.queryByText("agent.section.results")).not.toBeInTheDocument();
    expect(screen.queryByText("agent.section.nextSteps")).not.toBeInTheDocument();
    let assistantMessage: agentApi.AgentConversationMessage | undefined;
    await waitFor(() => {
      const calls = vi.mocked(agentApi.saveAgentConversationState).mock.calls;
      assistantMessage = calls
        .flatMap(([messages]) => messages as agentApi.AgentConversationMessage[])
        .filter((item) => item.role === "assistant")
        .find((message) => message?.audit?.evidence?.web_search);
      expect(assistantMessage?.audit?.evidence?.web_search?.tool_statuses).toEqual({
        nexusmods_search: "succeeded",
      });
    });
    expect(assistantMessage?.audit?.evidence?.web_search?.tool_result_counts).toEqual({
      nexusmods_search: 2,
    });
  });

  it("renders persisted audit actions from loaded conversation state", async () => {
    vi.mocked(agentApi.fetchAgentConversationState).mockResolvedValue({
      active_session_id: "sess_test",
      messages: [
        {
          id: "assistant_1",
          role: "assistant",
          text: "ok",
          session_id: "sess_test",
          response_cards: {
            analysis: ["任务分析：需要扩展在线来源。"],
            evidence: ["证据：NexusMods 没有返回足够候选。"],
            conclusion: ["结论：建议扩展到 LoversLab。"],
          },
          audit: {
            evidence: {
              web_search: {
                enabled: true,
                queried: false,
                tools: ["online_gate"],
                tool_statuses: { online_gate: "skipped" },
                tool_result_counts: { online_gate: 0 },
              },
            },
            conclusion: {
              recommended_action: "expand_online_sources_and_narrow_scope",
              action_payload: {
                expand_online_candidates: [{ id: "loverslab_google", label: "LoversLab" }],
              },
            },
          },
        },
      ],
    });

    renderPage();

    expect(await screen.findByText("任务分析：需要扩展在线来源。")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "继续查 LoversLab 来源的结果" })).toBeInTheDocument();
  });

  it("maps nexusmods_search candidate to nexusmods source", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        understanding: ["u"],
        filters: [],
        results: [],
        next_steps: ["n1"],
      },
      audit: {
        conclusion: {
          recommended_action: "expand_online_sources_and_narrow_scope",
          expand_online_candidates: ["nexusmods_search"],
        },
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const candidateButton = await screen.findByRole("button", { name: "继续查 NexusMods 来源的结果" });
    fireEvent.click(candidateButton);

    const sourceSelect = screen.getByDisplayValue("discover.sourceNexusmods") as HTMLSelectElement;
    expect(sourceSelect.value).toBe("nexusmods");
    expect((input as HTMLInputElement).value).toContain("NexusMods");
  });

  it("prefers action_payload.expand_online_candidates when provided", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        understanding: ["u"],
        filters: [],
        results: [],
        next_steps: ["n1"],
      },
      audit: {
        conclusion: {
          recommended_action: "expand_online_sources_and_narrow_scope",
          action_payload: {
            expand_online_candidates: [{ id: "loverslab_google", label: "LoversLab" }],
          },
        },
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const candidateButton = await screen.findByRole("button", { name: "继续查 LoversLab 来源的结果" });
    fireEvent.click(candidateButton);

    const sourceSelect = screen.getByDisplayValue("discover.sourceLoverslab") as HTMLSelectElement;
    expect(sourceSelect.value).toBe("loverslab");
  });

  it("renders narrow scope field buttons from action_payload and applies input template", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        understanding: ["u"],
        filters: [],
        results: [],
        next_steps: ["n1"],
      },
      audit: {
        conclusion: {
          recommended_action: "narrow_query_scope",
          action_payload: {
            narrow_scope_fields: ["game", "keywords"],
          },
        },
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const gameButton = await screen.findByRole("button", { name: "我想限定目标游戏" });
    expect(gameButton).toBeInTheDocument();
    fireEvent.click(gameButton);
    expect((input as HTMLInputElement).value).toContain("我想限定目标游戏为");
  });

  it("renders review target button and applies review template", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        understanding: ["u"],
        filters: [],
        results: [],
        next_steps: ["n1"],
      },
      audit: {
        conclusion: {
          recommended_action: "review_memory_signals",
          action_payload: {
            review_targets: ["memory_signals"],
          },
        },
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const reviewButton = await screen.findByRole("button", { name: "请解释你参考了哪些记忆信号" });
    fireEvent.click(reviewButton);
    expect((input as HTMLInputElement).value).toContain("请解释你参考了哪些记忆信号");
  });

  it("renders conflict field button and applies confirm template", async () => {
    vi.mocked(agentApi.chatWithAgent).mockResolvedValue({
      answer: "ok",
      used_llm: false,
      matches: [],
      response_cards: {
        understanding: ["u"],
        filters: [],
        results: [],
        next_steps: ["n1"],
      },
      audit: {
        conclusion: {
          recommended_action: "clarify_memory_conflict",
          action_payload: {
            conflict_fields: ["game"],
          },
        },
      },
    });

    renderPage();

    const input = await screen.findByPlaceholderText("agent.placeholder");
    fireEvent.change(input, { target: { value: "test query" } });
    fireEvent.keyDown(input, { key: "Enter" });

    const conflictButton = await screen.findByRole("button", { name: "这次目标游戏应该按哪个来查？" });
    fireEvent.click(conflictButton);
    expect((input as HTMLInputElement).value).toContain("这次目标游戏应该按哪个来查？");
  });
});
