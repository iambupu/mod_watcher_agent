# 文档索引

本目录收纳 Mod Watcher Agent 的设计说明、Agent 模块演进记录和配套资源。根目录 README 继续面向安装、启动和日常使用；这里面向开发、审查和后续维护。

## Agent 模块

- [Agent 模块技术实现文档](./agent-technical-implementation.md)：说明当前 Agent 请求链路、模块边界、数据契约和 evidence 生成方式。
- [Agent 语义大脑三批迭代技术方案](./agent-semantic-brain-iteration-plan.md)：记录 `SemanticStrategy`、候选语义裁判和旧规划链收敛的设计取舍。
- [Agent 语义大脑迭代任务清单](./agent-semantic-brain-tasks.md)：列出三批改造的落地状态、审查重点和推荐回归入口。

## 审查与验证入口

Agent 相关改动建议至少按影响范围选择以下命令验证：

```powershell
cd backend
python scripts/run_agent_quality_gate.py
python -m pytest app/tests/test_agent_runtime_graph.py
python -m pytest app/tests/test_agent_tool_planner_executor.py
python -m pytest app/tests/test_routes_agent_chat_context.py
```

跨前后端改动建议使用仓库级基线：

```powershell
python -m ruff check backend/app
python -m pytest backend/app/tests -q
npx tsc -p frontend/tsconfig.json --noEmit --noUnusedLocals --noUnusedParameters
cd frontend
npm test
```

## 资源文件

- `mwlogo.png`：README 顶部 Logo。
- `Mod Watcher Agent.png`：README 中展示的界面截图。
