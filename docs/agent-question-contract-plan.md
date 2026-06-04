# Agent 问题契约通用技术方案

## 背景

智能助手通常会经历三个阶段：

1. 理解用户问题。
2. 检索或召回候选。
3. 整合候选并生成回答。

当用户问题包含范围、排除、优先级或“只看/不要/对比/推荐”等自然语言约束时，仅靠查询词扩展容易产生歧义。宽召回可以带回有用上下文，但如果回答阶段没有明确边界，LLM 可能把“弱相关候选”包装成“直接满足需求”的结果。

本方案引入 `Question Contract`，让 Agent 在执行检索和回答前，先生成一份结构化任务契约。契约用于约束后续的查询扩展、候选分型、回答组织和最终审计。

## 适用范围

本方案适用于所有需要自然语言检索、推荐、比较、问答或建议的 Agent 场景，包括但不限于：

- 用户要求“只看某类结果”。
- 用户要求“排除某类结果”。
- 用户表达了主目标和辅助条件。
- 用户问题允许宽召回，但最终回答需要严格分层。
- 候选结果中可能同时存在直接命中、辅助上下文、弱相关和不相关项。

本方案不是某一类内容、某一类 Mod、某一类成人内容或某个数据源的专用方案。

## 目标

- 在检索前显式定义本轮任务边界。
- 区分“召回扩展”和“回答约束”。
- 允许宽召回，但要求回答阶段按契约筛选和分组。
- 防止 LLM 把辅助项、弱相关项或不符合项包装成直接推荐。
- 为日志、调试和测试提供可审计的中间产物。
- 支持规则回退，避免完全依赖 LLM 生成契约。

## 非目标

- 不把所有语义判断都提前变成数据库硬过滤。
- 不禁止召回弱相关或辅助候选。
- 不要求输出隐藏推理链。
- 不把查询扩展词反向升级为用户主目标。
- 不把某个示例场景写死到通用流程中。

## 核心原则

### 1. 召回可以宽，回答必须守约

召回阶段可以使用扩展词、同义词、相关概念和历史上下文提升覆盖率。

回答阶段必须根据契约区分：

- 直接满足用户目标的候选。
- 仅提供辅助上下文的候选。
- 不适合本轮回答的候选。
- 证据不足、需要确认的候选。

### 2. 扩展词不能改变用户目标

例如某个扩展词可以帮助召回依赖、兼容项或背景资料，但不能因此把这些辅助候选当成用户主目标的直接结果。

### 3. `只看/不要/排除` 是回答约束

这些词不一定要求查询阶段完全过滤，但最终主回答必须遵守。辅助项如果展示，必须明确标注其不是主结果。

### 4. 契约必须结构化

契约应输出 JSON 或等价结构，供后续模块消费，而不是只把“请理解用户意图”写进 prompt。

## 总体流程

```text
用户问题
  -> Question Contract 生成
  -> 查询计划与宽召回
  -> Candidate Judge 候选分型
  -> Answer Composer 分组回答
  -> Final Contract Audit 最终审计
```

## Question Contract Schema

建议 schema：

```json
{
  "primary_goal": "用户本轮主要目标",
  "task_type": "search|recommendation|comparison|advisory|detail|unknown",
  "hard_constraints": {
    "game": null,
    "source": null,
    "category": null,
    "content_type": null,
    "adult_content": null,
    "time_range": null,
    "sort": null
  },
  "direct_match_definition": [
    "什么条件下候选可以算直接满足用户目标"
  ],
  "support_context_definition": [
    "什么条件下候选只能算辅助上下文"
  ],
  "reject_as_primary": [
    "不得作为主结果的候选类型或违例原因"
  ],
  "recall_expansion_terms": [
    "仅用于召回的扩展词"
  ],
  "ranking_policy": {
    "prefer": [],
    "deprioritize": []
  },
  "answer_policy": {
    "main_results": "only_direct_match",
    "support_context": "separate_section",
    "uncertain_items": "mark_uncertain",
    "insufficient_direct_matches": "state_insufficient_before_support_items"
  }
}
```

字段说明：

- `primary_goal`：用户真正要完成的主要目标。
- `task_type`：本轮任务类型，用于选择回答形态。
- `hard_constraints`：用户明确说死的条件；不能由记忆或扩展词随意补充。
- `direct_match_definition`：主结果准入规则。
- `support_context_definition`：辅助候选的展示规则。
- `reject_as_primary`：不能进入主结果的违例类型。
- `recall_expansion_terms`：召回用扩展词，只服务检索，不改变主目标。
- `ranking_policy`：排序和重排时的偏好。
- `answer_policy`：回答层必须遵守的展示策略。

## 候选分型

召回完成后，每个候选都要基于 `Question Contract` 被标注。

建议输出：

```json
{
  "items": [
    {
      "id": 123,
      "fit_type": "direct_match",
      "score": 0.91,
      "evidence": ["支持它直接满足用户目标的证据"],
      "violations": []
    },
    {
      "id": 456,
      "fit_type": "support_context",
      "score": 0.62,
      "evidence": ["支持它作为辅助上下文的证据"],
      "violations": ["not_primary_result"]
    }
  ]
}
```

`fit_type` 枚举：

- `direct_match`：可以进入主结果或主推荐。
- `support_context`：只能作为辅助、依赖、兼容、背景或补充信息。
- `off_scope`：默认不展示，除非用户要求解释排除原因。
- `uncertain`：证据不足；默认不进入主结果，展示时必须标注不确定。

## 回答组织规则

回答层必须按照候选分型组织内容。

推荐结构：

```text
直接符合本轮目标的结果
- ...

辅助上下文，不作为主结果
- ...

证据不足或需要确认
- ...
```

如果 `direct_match` 数量不足，必须先说明：

```text
当前候选中没有足够明确的直接命中项。
下面内容仅作为辅助参考，不作为本轮主推荐。
```

禁止表达模式：

```text
虽然它不满足主目标，但因为可以辅助主目标，所以作为主结果推荐。
```

允许表达模式：

```text
它更像辅助上下文，不作为本轮主结果；如果你继续处理相关方案，它可能用于兼容、依赖或搭配判断。
```

## 模块改动建议

### `semantic_brain`

新增或扩展问题契约生成能力。

职责：

- 从用户问题和上下文中生成 `QuestionContract`。
- 区分硬约束、软信号和召回扩展词。
- 不把历史偏好或扩展词升级成用户本轮硬约束。

失败回退：

- LLM 输出非法 JSON 时使用规则契约。
- 置信度低时保留宽召回，但回答层启用保守分型。

### `query_planner`

职责：

- 消费 `hard_constraints` 和 `recall_expansion_terms`。
- 继续处理来源、游戏、时间、排序等结构化过滤。
- 将扩展词仅作为召回信号，不作为主目标证据。

原则：

- 明确约束可以进入硬过滤。
- 模糊语义优先进入召回或排序信号。
- 契约中的 `content_type` 不必总是转成 SQL 条件，可交给候选分型和回答层处理。

### `candidate_judge`

可在现有 reranker 基础上升级。

职责：

- 基于 `QuestionContract` 给候选打 `fit_type`。
- 输出 `score`、`evidence`、`violations`。
- 不只做相关性排序，还要判断候选是否可作为主结果。

### `answer_service`

职责：

- 接收原始问题、契约、候选分型结果。
- 主结果只使用 `direct_match`。
- 辅助候选单独分组。
- 证据不足候选必须标注不确定。
- 不得把 `support_context` 或 `off_scope` 包装成主结果。

### `final_audit`

可作为轻量后处理。

职责：

- 检查最终文本是否违反 `QuestionContract`。
- 重点检查主结果区是否包含非 `direct_match`。
- 检查是否出现禁止表达模式。
- 失败时要求重写，或降级为规则化 fallback 回答。

## 日志与可观测性

建议记录：

```text
agent.contract task_type=... primary_goal=... hard_constraints=...
agent.recall expansion_terms=... hard_filters=...
agent.candidate_judge direct=... support=... off_scope=... uncertain=...
agent.answer_policy main_results=... insufficient_direct=...
agent.final_audit status=...
```

排查 bad case 时，按层定位：

- 契约生成错：`primary_goal` 或 `hard_constraints` 错。
- 召回过窄：`recall_expansion_terms` 不足。
- 召回过宽但可接受：候选多为 `support_context`。
- 候选分型错：`fit_type` 与证据不一致。
- 回答错：主结果区违反 `answer_policy`。

## 测试策略

### 用例 1：宽召回但窄回答

输入包含明确主目标，候选包含直接命中和辅助项。

期望：

- 直接命中进入主结果。
- 辅助项进入单独分组。
- 主结果标题不能声称所有候选都符合主目标。

### 用例 2：没有直接命中

输入包含明确主目标，但候选全部为辅助项或弱相关项。

期望：

- 回答先说明直接命中不足。
- 不硬凑主推荐。
- 辅助项只能作为参考展示。

### 用例 3：排除约束

输入包含“不要/排除/不看”。

期望：

- 被排除类型不能进入主结果。
- 如召回阶段出现，应在分型中标记 `off_scope` 或对应 violation。

### 用例 4：比较或建议任务

输入是比较、安装风险、替代方案或搭配建议。

期望：

- 契约的 `task_type` 不应误判成普通搜索。
- 辅助上下文可以进入分析，但必须明确其角色。

### 用例 5：历史上下文不覆盖本轮约束

历史偏好和当前用户输入冲突。

期望：

- 当前输入优先。
- 历史偏好最多作为软信号。
- 契约中保留可审计 evidence。

## 分阶段落地

### 阶段 1：规则契约与回答分组

- 用规则生成基础 `QuestionContract`。
- 覆盖常见的“只看、排除、推荐、对比、安装风险”。
- 修改回答层，让主结果与辅助上下文分组。

收益：最快降低回答包装错误。

### 阶段 2：候选分型结构化

- 升级 reranker 或新增 `candidate_judge`。
- 输出 `fit_type`、`evidence`、`violations`。
- 回答层根据 `fit_type` 选择内容。

收益：减少 prompt 漂移，提升可测试性。

### 阶段 3：LLM 契约生成

- 在 `semantic_brain` 中加入 LLM contract 生成。
- 使用 schema 校验。
- 非法、低置信度或不完整时回退到规则契约。

收益：支持复杂自然语言意图。

### 阶段 4：最终审计

- 回答生成后执行 contract audit。
- 发现主结果违反契约时重写或降级。

收益：给最终输出增加最后一道防线。

## 风险与控制

- 风险：契约生成过度保守。
  控制：保留 `support_context` 分组，不直接丢弃所有非主结果候选。

- 风险：契约生成过度扩张。
  控制：硬约束只接受用户明示内容；扩展词只用于召回。

- 风险：LLM 输出格式不稳定。
  控制：schema 校验、JSON 修复、规则回退。

- 风险：延迟增加。
  控制：先用规则契约和本地分型；LLM contract 按需启用。

- 风险：模块继续膨胀。
  控制：拆清职责，`contract` 定义任务边界，`retrieval` 负责召回，`candidate_judge` 负责分型，`answer_service` 负责表达，`final_audit` 负责输出校验。

## 示例：主目标与辅助项分离

用户输入：

```text
只看某类主结果
```

候选中同时存在：

- 直接属于该类别的条目。
- 仅提供依赖、兼容、背景或搭配价值的条目。
- 与主目标弱相关但不能作为主结果的条目。

契约应表达：

```json
{
  "primary_goal": "寻找某类主结果",
  "hard_constraints": {
    "content_type": "用户明确要求的类型"
  },
  "direct_match_definition": [
    "候选本体必须属于该类型"
  ],
  "support_context_definition": [
    "依赖、兼容、背景、搭配项只能作为辅助上下文"
  ],
  "answer_policy": {
    "main_results": "only_direct_match",
    "support_context": "separate_section"
  }
}
```

回答应区分：

```text
直接符合的结果
- ...

辅助上下文，不作为主结果
- ...
```

## 结论

`Question Contract` 的作用是把 Agent 的“先明确任务边界，再执行和回答”显式化、结构化、可审计化。

它不限制召回阶段的探索能力，但要求候选分型和回答组织严格遵守用户本轮目标。这样可以保留宽召回的价值，同时避免最终回答把辅助项或弱相关项包装成直接结果。
