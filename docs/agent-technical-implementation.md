# Mod Agent 当前实现方案（backend）

该文档描述当前仓库中 `mod_watcher_agent` 后端 Agent 的实际实现链路（非设计草案），用于定位检索、排序和误召回问题。

## 0. 一句话总览

Agent 的入口是一个 LangGraph 工作流：  
`/api/agent/chat` 与 `/api/agent/mod-detail` → `AgentRuntime` → `mod_search_graph` 节点流。  
普通查询走“理解→检索→融合排序→回答”，详情查询走“摘要直达→模块详情回答”。

---

## 1. 入口与请求路由

### 1.1 HTTP 路由
- `POST /api/agent/chat`：`backend/app/api/routes_agent.py`
  - `AgentService.chat()` → `AgentRuntime.chat()`
- `POST /api/agent/mod-detail`：`AgentRuntime.ask_mod_detail()`
- 其他会话状态接口位于同文件，不影响检索/排序主链路。

### 1.2 运行时入口
- `backend/app/services/agent/runtime.py`
  - `chat`：
    - 如果用户消息包含“详细解析/详情”且命中本地 Mod 标题，先走详情分支（`/mod-detail` 相同）。
    - 否则进入 `request_kind=chat` 的图执行。
  - `ask_mod_detail`：
    - 强制走 `request_kind=mod_detail`，跳过通用检索。

---

## 2. 主工作流状态图（LangGraph）

`backend/app/services/agent/workflows/mod_search_graph.py`

```
load_state
  -> summarize_context
    -> diagnose_query? / generate_detail_answer
    diagnose_query
      -> plan_tools
      -> staged_retrieval
      -> rank_results
      -> generate_answer
      -> reflect
      -> persist_result
  -> ... (persist_result)
```

`mod_detail` 路径：`summarize_context -> generate_detail_answer -> persist_result`，不经过检索与排序。

`graph_state` 见 `backend/app/services/agent/workflows/graph_state.py`，包含：
- `chat_request`, `detail_request`, `query_plan`, `query_diagnosis`, `tool_plan`
- `staged_results`, `online_results`, `matches`
- `retrieval_evidence`, `trace`, `response`, `evidence_id` 等。

---

## 3. 关键阶段说明

### 3.1 summarize_context
`backend/app/services/agent/context/context_stage.py`
- 读取当前请求和会话上下文（`ContextSummaryTool`），产出：
  - `running_summary`
  - `active_constraints`
  - `last_query_context`
  - `shown_mod_titles`
  - `tool_traces` / `reflection_notes`（用于后续审计和回放）

### 3.2 diagnose_query（理解阶段）
`backend/app/services/agent/workflows/understanding_stages.py`

调用 `TaskUnderstandingTool`（`backend/app/services/agent/tools/task_understanding_tool.py`）完成：
1. 上下文读取（短期/长期记忆）  
2. 历史与上下文诊断（可选 LLM）  
3. Semantic Strategy 生成  
4. 执行计划生成（`ExecutorQueryTool`）  
5. 查询计划标准化（`normalize_query_plan`）  
6. `QueryDiagnosis`（意图、已知槽位、缺失槽位、置信度、是否要澄清）

### 3.3 plan_tools（工具计划）
`backend/app/services/agent/tools/tool_planner_tool.py`
- 使用 `ToolPlannerTool -> planning/tool_planner.py`，输入为 `query_diagnosis` + `preferences`。
- 输出 `tool_plan`，核心字段：
  - `parallel_groups`: 本地组 + 在线组（当前执行器按阶段执行：先跑本地，再基于门槛判断是否跑在线）
  - `online_steps`: 被允许在线抓取的工具
  - `degraded_reasons`: 能力缺失/策略降级记录
  - `tool_policy_evidence`: 策略分数与策略名（用于审计）
- 规则特征：
  - 先做本地（structured_sql + sqlite_fts）
  - 再按策略做在线补充
  - 支持 `local_only` 和 `online_recall_mode(narrow|broad)`。

### 3.4 staged_retrieval（分段检索）
`backend/app/services/agent/workflows/search_stages.py -> execute_retrieval_stage`
  
`ToolExecutorTool`（`backend/app/services/agent/tools/tool_executor_tool.py`）执行：

#### 本地检索
- `LocalDbSearchTool`：
  - 调 `mod_search_service.query_mods_with_plan(query, plan)`
  - 本地 SQL/FTS + 缓存条件先于在线执行
- 记录 evidence：`stage=local_retrieval`

#### 在线检索
- `WebSearchTool`：
  - 可调用 `NexusModsSearchTool`、`LoversLabGoogleSearchTool`、`LoversLabSearchScrapeTool`
  - 根据 `tool_plan` 与 `online_recall_mode` 决定可执行集合
- 是否触发在线检索由 `_online_retrieval_decision` 控制：
  - 来源显式约束（`sources`）
  - 是否有 distinct term
  - 是否 open discovery
  - 是否是生态/风险/机制类查询（`_is_ecosystem_query`）
  - 本地结果质量（数量、来源多样性、摘要覆盖）
- 记录 evidence：`stage=online_retrieval` + 失败/降级原因

---

## 4. 查询计划（query_plan）与有效查询串（effective_query）

### 4.1 query_plan 结构
`query_plan` 由规划/归一化后进入 `SearchPlan`，关键字段见：
`backend/app/services/agent/search_types.py`

常用字段包括：
- `keywords`, `excluded_keywords`
- `games`, `game_domains`, `categories`, `category_match_mode`, `category_hints`
- `sources`, `excluded_sources`
- `author`, `exact_title`, `external_id`, `source_url`
- `tags`, `summary_languages`, `excluded_summary_languages`
- `requirement_terms`, `compatibility_terms`
- `adult_content`, `sort_field`, `sort_order`, `limit`
- `open_discovery`, `retrieval_mode`, `keyword_match_mode` 等。

### 4.2 effective_query 生成
`ToolExecutorTool._effective_search_query`
- `visible_query = strip_scope(query)`：去掉 `[scope]` 追加块
- 若 `distinctive_query_terms(visible_query)` 为空，则补充：
1. `plan.keywords`
2. `plan.categories`
- 去重后返回拼接串供本地 + 在线检索复用。

该行为的意义：对于过短/不具备区分能力的文本，用结构化槽位补齐检索召回，不让检索因关键字过少而空。

---

## 5. 排序与过滤（rank_results）

### 5.1 候选融合链
`CandidateRankingTool`（`backend/app/services/agent/tools/candidate_ranking_tool.py`）顺序：
1. `ResultFusionRankerTool`（融合去重/排序/过滤）
2. `MatchMaterializerTool`（物化为 `AgentModMatch`）
3. 非开放发现路径：`LlmCandidateValidatorTool` 软校验
4. 开放发现路径：`CandidateSemanticJudgeTool` 语义裁判
5. 无结果回退：`CandidateRecoveryTool`（本地窄范围重检索）

### 5.2 融合与排序规则
`backend/app/services/agent/result_merger.py`
核心函数顺序：
- `merge_results`：按 `(source,id)` 去重并融合重复候选（`fuse_duplicate_results`）
- `sort_results`：按 `plan.sort_field` 排序，`relevance` 时再加三类权重  
  - `_category_hint_score`
  - `_semantic_hint_score`
  - `_keyword_group_score`
- `filter_by_distinctive_terms`：
  - 先按语义锚点组打分（`_query_plan_anchor_groups`）
  - 若无命中则回退到 `distinctive_query_terms` 兜底过滤
- 软/硬过滤顺序（固定顺序）：
  - `filter_by_adult_content`
  - `filter_semantic_soft_rejects`
  - `filter_by_exact_title`
  - `filter_excluded_titles`
  - `filter_excluded_keywords`

### 5.3 语义锚点分组得分（与“词边界”）
`_query_plan_anchor_groups_from_field` 由 `plan` 中:
- `_agent_ranking_semantic_anchors`
- `_agent_semantic_anchors`
提取锚点，扩展 `expanded_terms / matched_concepts / category_aliases` 后形成分组，带 source 权重参与 `_score_anchor_group`。

匹配判断逻辑（`_term_in_haystack`）：
- 若 term 包含空格：使用**包含匹配**
- 纯英文字母数字词：使用正则边界匹配（`(?<![a-z0-9])... (?![a-z0-9])`）
- 中文/短语：回退为子串包含匹配  
这意味着 `"bimbo"` 这种短 token 会用边界匹配，避免误切“a+数字/字母”衔接上下文内的部分命中。

---

## 6. 在线/本地分阶段与候选证据链

### 6.1 Evidence 结构
`backend/app/services/agent/retrieval_evidence.py`
- `append_retrieval_evidence` 统一写入 `stage/tool/status/count/reason/fields/evidence_id`。
- 每个工具、每一步都有独立片段 `fragment_id`，用于 UI/审计/排障。

### 6.2 Trace
`backend/app/services/agent/tracing/search_trace.py`
- 所有节点在 LangGraph 内写入 `trace`（`step/status/duration_ms/evidence_id`）。
- `finish_trace`/`fail_trace` 用于成功/失败路径。

### 6.3 最终响应封装
`backend/app/services/agent/workflows/response_finalization.py`
- 注入 `memory_evidence`
- 写回上下文快照到 memory（`MemoryWritebackTool`）
- 生成 audit（`audit_service` + `reflection`）并做一致性标注
- 回填 `evidence_id`, `used_llm`, `understanding` 等给前端。

---

## 7. 本地检索与 SQL 计划细节（数据库侧）

`backend/app/services/agent/mod_search_service.py`
- 先构建 FTS：
  - 若 `sort_field` 为 relevance，尝试 `query_mods_fts`。
- 再构建主查询（含强制条件、关键词条件、排除条件、时间窗口、exact_title、作者、来源等）。
- 用 `text_score` + `identity_score` + `category_hint_score` 给候选打分并排序。
- 关键约束/关键字在 `_build_mod_query_from_plan` 与 `_db_fuzzy_keywords` 中体现。

---

## 8. 详情链路

`ModDetailAnswerTool`（`backend/app/services/agent/tools/mod_detail_answer_tool.py`）：
1. 通过 `mod_id` 找到实体
2. 构建单条 `AgentModMatch`
3. 有 LLM 则调用 `AgentAnswerService.answer_detail`
4. 无 LLM 或失败则回退到结构化本地信息文本
5. 返回 `response_cards` 与 `used_llm` 标记

---

## 9. 异常/退化路径

- 本地检索无结果：
  - 可触发在线检索（若计划允许且命中策略）
- 排序后为空：
  - `CandidateRecoveryTool` 按 `sort_field` 重查并放宽局部约束
- LLM 失效：
  - 候选校验和语义裁判会降级为“跳过/降级”
- 模板问题/解析失败：
  - 继续返回本地候选或 fallback 内容，不阻塞主路径（除非图执行失败）

---

## 10. 当前版本的可维护性提示（建议排障优先级）

1. 检查 `query_plan` 是否已进入 `open_discovery`  
   - 对应关键词放宽程度、`keyword_match_mode`、`apply_distinctive_filter` 分支不同
2. 检查 `tool_plan.tool_policy_evidence.degraded_reasons`  
   - 先确认是否因能力缺失导致在线被降级
3. 检查 `staged_retrieval` 的 evidence 阶段计数  
   - 看 `local_retrieval` 与 `online_retrieval` 是否按预期触发
4. 若“误召回作者词”：
   - 看 `query_plan.intent` 或 `query_plan.author` 是否被误判（设置不当）
   - 看 `effective_query` 是否额外引入了不该加的关键词
5. 若“相关性排序偏差”：
   - 看 `filter_by_distinctive_terms` 的命中/回退路径
   - 看 `_query_plan_anchor_groups` 和 `plan.semantic anchors` 是否空

---

## 11. 重要文件索引（便于改代码前速查）

- 路由与服务  
  - `backend/app/api/routes_agent.py`
  - `backend/app/services/agent/chat_service.py`
  - `backend/app/services/agent/runtime.py`
- 图与阶段  
  - `backend/app/services/agent/workflows/mod_search_graph.py`
  - `backend/app/services/agent/workflows/understanding_stages.py`
  - `backend/app/services/agent/workflows/search_stages.py`
  - `backend/app/services/agent/workflows/graph_state.py`
- 规划与诊断  
  - `backend/app/services/agent/query_planner.py`
  - `backend/app/services/agent/planning/query_diagnosis.py`
  - `backend/app/services/agent/tools/task_understanding_tool.py`
  - `backend/app/services/agent/tools/semantic_signal_tool.py`
- 检索工具  
  - `backend/app/services/agent/tools/tool_executor_tool.py`
  - `backend/app/services/agent/tools/local_db_search_tool.py`
  - `backend/app/services/agent/tools/web_search_tool.py`
  - `backend/app/services/agent/mod_search_service.py`
- 排名与校验  
  - `backend/app/services/agent/tools/candidate_ranking_tool.py`
  - `backend/app/services/agent/tools/result_fusion_ranker_tool.py`
  - `backend/app/services/agent/result_merger.py`
  - `backend/app/services/agent/tools/llm_candidate_validator_tool.py`
  - `backend/app/services/agent/judging/candidate_semantic_judge.py`
  - `backend/app/services/agent/tools/candidate_recovery_tool.py`
- 回答与响应  
  - `backend/app/services/agent/tools/chat_answer_tool.py`
  - `backend/app/services/agent/tools/answer_generation_tool.py`
  - `backend/app/services/agent/tools/response_card_builder_tool.py`
  - `backend/app/services/agent/workflows/response_finalization.py`
- 证据与观测  
  - `backend/app/services/agent/retrieval_evidence.py`
  - `backend/app/services/agent/tracing/search_trace.py`
