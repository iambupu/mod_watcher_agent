# CODE_STYLE.md - Mod Watcher Agent

本文档定义本仓库的代码风格与工程约定。目标是提高一致性、可维护性和可审查性。

## 1. 命名规范

### 1.1 Python（后端）

- 文件名：`snake_case.py`（如 `routes_mods.py`, `settings_service.py`）
- 类名：`PascalCase`（如 `SettingsService`）
- 函数/方法/变量：`snake_case`
- 常量：`UPPER_SNAKE_CASE`
- 私有辅助函数：前缀 `_`（如 `_redact_settings_for_response`）

### 1.2 TypeScript / React（前端）

- 组件文件：`PascalCase.tsx`（如 `RuleEditorPage.tsx`）
- 非组件模块：`camelCase.ts`（如 `queryClient.ts`, `uiStore.ts`）
- 变量/函数：`camelCase`
- 类型/接口：`PascalCase`
- Hook：`use` 前缀（如 `useSettingsSync`）

## 2. 目录与职责

### 2.1 后端

`backend/app` 下按职责分层：

- `api/`：HTTP 路由层（参数校验、协议转换）
- `services/`：业务逻辑层
- `models/`：SQLModel 持久化模型
- `schemas/`：请求/响应 schema
- `adapters/`：外部来源适配器
- `jobs/`：定时与手动任务

要求：
- 路由层尽量薄，复杂逻辑下沉到 service。
- 外部站点抓取与解析只放在 adapter 中。
- Agent 模块按计划器、工具、结果合并、回答生成拆分；不要把搜索工具调用、结果去重排序、LLM prompt 细节继续堆到 `chat_service.py`。

#### 2.1.1 Agent 模块职责

`backend/app/services/agent/` 的职责边界：

- `chat_service.py`：请求入口、限流、配置读取、query plan 生成、调用搜索编排器和回答服务、组装响应。
- `query_planner.py`：自然语言与 UI scope 到结构化查询计划的转换。
- `tools/`：单一来源搜索工具。Local DB、NexusMods、LoversLab Google、LoversLab scrape 需要统一输入/输出契约。
- `result_merger.py`：本地/在线结果合并、source/external_id 去重、排序、distinctive term 过滤、adult_content 最终过滤。
- `answer_service.py`：LLM 回答与详情解析 prompt。
- `response_builder.py`：把已确定结果转换为前端 response cards。

确定性规则必须在代码中实现并由测试覆盖，不交给 LLM 判断。

### 2.2 前端

`frontend/src` 下按职责分层：

- `pages/`：路由页面
- `components/`：复用组件
- `api/`：API 调用封装
- `stores/`：状态管理（Zustand）
- `app/`：应用级配置（router/queryClient/i18n）
- `types/`：共享类型

要求：
- 页面不直接拼接 API URL，统一走 `api/client.ts`。
- 通用 UI 与业务 UI 分离（`components/ui` vs 业务组件）。

## 3. API 与数据约定

- 后端路由统一挂载在 `/api/*`。
- 后端 schema 字段使用 `snake_case`（与数据库字段一致）；API 返回 `snake_case`，前端 TS 类型使用 `camelCase`。
- 数据库存储字段使用 `snake_case`。
- JSON 字符串字段使用 `_json` 后缀（如 `filters_json`）。

## 4. 导入与依赖

### 4.1 Python

- 导入分组：标准库 -> 第三方 -> 本地模块。
- 禁止 `import *`。
- 优先绝对导入：`from app.db import get_session`。

### 4.2 TypeScript

- 使用 `@/` 别名导入本地模块。
- 第三方包导入放在本地模块导入之前。

## 5. 错误处理与日志

### 5.1 后端

- 参数与资源错误使用 `HTTPException` 明确返回码。
- 外部调用异常要记录上下文日志，避免吞错。
- 任务执行统一落 `JobRun`/日志，不在路由中静默失败。

### 5.2 前端

- API 层统一抛错，页面层负责展示。
- 用户可操作流程要有可见状态（loading/success/error）。

## 6. 代码注释准则

代码注释会被视为后续维护准则，不能随意写成临时说明。

### 6.1 应该写注释的情况

- 说明业务不变量，例如 `source + external_id` 是跨来源去重身份。
- 说明安全或合规边界，例如“不下载 Mod 文件”“不绕过登录/年龄/权限”。
- 说明非显而易见的排序、过滤、fallback 或兼容逻辑。
- 说明为什么某段逻辑必须保持确定性，不能交给 LLM。
- 说明和旧数据、旧 API、旧前端状态兼容的原因。

### 6.2 不应该写注释的情况

- 不复述代码正在做什么，例如“创建列表”“遍历结果”“返回 response”。
- 不保留已经失效的历史解释。
- 不把 TODO 当成长期设计；需要后续处理时写入 issue、计划文档或测试。

### 6.3 修改要求

- 修改被注释描述的逻辑时，必须同步更新注释。
- 注释描述的是规则时，必须补测试锁定该规则。
- 注释、测试和文档冲突时，先修正冲突，再继续实现。

## 7. 测试规范

### 7.1 后端（pytest）

- 测试文件命名：`test_*.py`。
- 测试目录：`backend/app/tests/`（主要测试）与 `backend/tests/`（根级 schema 测试）。
- 异步测试使用 `pytest-asyncio`。

### 7.2 前端（Vitest）

- 测试文件与组件同目录或 `__tests__` 目录。
- UI 文案和交互行为都应有关键路径测试。

## 8. 提交前检查

### 后端

```bash
cd backend
pip install -e .[dev]
pytest
```

### 前端

```bash
cd frontend
npm install
npm run lint
npm run test
npm run build
```

## 9. 安全与配置

- 禁止提交任何密钥、令牌、Webhook。
- `.env` 仅本地使用，参考 `.env.example`。
- 对敏感配置返回必须脱敏（例如 `********`）。
- 默认本地模式下，遵循 `LOCAL_ONLY_API` 的访问限制设计。

## 10. 禁止事项

- 不要在组件中直接写死后端地址。
- 不要在 service 层做 UI 语义拼装。
- 不要绕过 adapter 直接在其他层解析外部 HTML。
- 不要把临时调试文件、日志、数据库产物提交到仓库。
