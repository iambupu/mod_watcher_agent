# Agent 语义大脑迭代任务清单

本文档配套 [`agent-semantic-brain-iteration-plan.md`](./agent-semantic-brain-iteration-plan.md)，记录三批语义大脑改造的执行状态、审查重点和回归入口。

## 当前执行状态

| 批次 | 状态 | 已落地重点 |
| --- | --- | --- |
| 批次一 | 已完成核心开发 | 新增 `semantic_brain` 包、`SemanticStrategy` schema、prompt、tool、adapter 和回归测试 |
| 批次二 | 已完成核心开发 | 新增 `judging` 包，开放发现候选进入 `CandidateSemanticJudgeTool`，response evidence 展示 judge 状态 |
| 批次三 | 已完成核心开发 | `SemanticStrategy` 成为主决策对象，`query_plan` 作为 executor 兼容合同，`ToolPlannerTool` 映射为 `ToolPolicy` |

说明：当前代码已完成前三批核心链路，但不是每个早期计划项都以独立文件落地。例如 candidate judge 的 `gaps` 当前作为 evidence 和回答提示使用，没有单独的 `result_gap_analyzer.py` 补查循环模块。

## 批次一检查点

- [x] 新增 `backend/app/services/agent/semantic_brain/` 包。
- [x] 定义 `SemanticStrategy`、`SemanticHardFilters`、`SemanticStrategyResult`。
- [x] 增加 `MW_AGENT_SEMANTIC_STRATEGY_ENABLED` 开关。
- [x] Prompt 限制 LLM 只输出策略 JSON，不输出 SQL、URL 或工具调用。
- [x] LLM JSON 解析失败时尝试修复，失败后 fallback。
- [x] `TaskUnderstandingTool` 接入 `SemanticStrategyTool`。
- [x] strategy evidence 暴露到 understanding / audit。

推荐验证：

```powershell
cd backend
python -m pytest app/tests/test_agent_semantic_strategy_tool.py
python -m pytest app/tests/test_agent_query_diagnosis.py
python -m pytest app/tests/test_routes_agent_chat_context.py
```

## 批次二检查点

- [x] 新增 `backend/app/services/agent/judging/` 包。
- [x] 新增 `candidate_semantic_judge.py` 和 `candidate_semantic_judge_prompt.py`。
- [x] judge 输出 `high | medium | low | reject`、group、reason、gaps。
- [x] `CandidateRankingTool` 接入 `CandidateSemanticJudgeTool`。
- [x] 开放发现路径保留宽召回策略，避免过早 distinctive hard filter。
- [x] LLM 不可用或开关关闭时回退确定性排序。
- [ ] 独立 `result_gap_analyzer.py` 补查循环未落地；当前 `gaps` 只进入 evidence 和回答提示。

推荐验证：

```powershell
cd backend
python -m pytest app/tests/test_agent_candidate_semantic_judge_tool.py
python -m pytest app/tests/test_agent_candidate_ranking_tool.py
python -m pytest app/tests/test_agent_local_db_tool.py
python -m pytest app/tests/test_agent_answer_generation_tool.py
```

## 批次三检查点

- [x] `SemanticStrategy` 成为主决策对象。
- [x] `query_plan` 降级为 executor 兼容输入。
- [x] `tool_planner.py` 改为 `SemanticStrategy -> ToolPolicy` 映射。
- [x] `query_diagnosis` 侧重解释 strategy、hard filters、soft signals 和 missing info。
- [x] audit 保持事后校验，不反向改写检索策略。
- [x] 当前代码没有 `MW_AGENT_SEMANTIC_STRATEGY_PRIMARY` 回滚开关；降级通过 `MW_AGENT_SEMANTIC_STRATEGY_ENABLED=false` 进入 fallback strategy。

推荐验证：

```powershell
cd backend
python scripts/run_agent_quality_gate.py
python -m pytest app/tests/test_agent_runtime_graph.py
python -m pytest app/tests/test_agent_tool_planner_executor.py
python -m pytest app/tests/test_agent_context_memory_selection.py
python -m pytest app/tests/test_routes_agent_chat_context.py
```

## 代码审查通用清单

- [ ] LLM 输出被 schema 校验，不能直接穿透到 SQL、URL 或工具白名单。
- [ ] 当前用户输入优先于 history、memory 和长期偏好。
- [ ] 只有用户明确表达的来源、游戏、标题、ID、URL、排除条件会进入 hard filter。
- [ ] 开放发现问题不会被 categories、tags、requirement terms、compatibility terms 过早强过滤。
- [ ] LLM 不可用时有确定性 fallback。
- [ ] evidence 能解释策略、检索、候选裁判和降级原因。
- [ ] 回答只引用 matches 或 judge 后的候选，不编造来源、版本、链接和兼容结论。
- [ ] audit 只做事后检查，不作为主决策层。

