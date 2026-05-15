# CODE_STYLE.md — Mod Watcher Agent

## 命名约定

### 文件命名

| 类型 | 约定 | 示例 |
|---|---|---|
| Python 模块 | `snake_case` | `discovery_service.py`, `routes_mods.py` |
| 模型文件 | 单数名词 | `mod.py`, `watch_rule.py` |
| 测试文件 | `test_` 前缀 + 模块名 | `test_filter_service.py`, `test_nexus_adapter.py` |
| TypeScript 组件 (页面) | PascalCase | `Dashboard.tsx`, `Discover.tsx` |
| TypeScript 组件 (UI) | PascalCase | `ModCard.tsx`, `RuleEditor.tsx` |
| TypeScript 工具模块 | camelCase | `queryClient.ts`, `uiStore.ts` |
| API 模块 | camelCase, 按资源 | `mods.ts`, `favorites.ts`, `client.ts` |
| 国际化资源 | BCP-47 语言标签 | `zh-CN.json`, `en-US.json`, `ja-JP.json` |
| 文档 | kebab-case | `api-contract.md`, `source-adapters.md` |

### 类/函数/变量命名

| 类型 | Python | TypeScript |
|---|---|---|
| 类 | `PascalCase` — `DiscoveryService`, `SourceAdapter`, `FilterService` | `PascalCase` — `ModCard`, `RuleEditor`, `LanguageToggle` |
| 函数/方法 | `snake_case` — `discover_from_rule()`, `apply_filters()`, `init_db()` | `camelCase` — `handleSubmit()`, `toggleSidebar()` |
| 私有方法 | `_` 前缀 — `_filter_by_keywords()`, `_run_job_with_logging()` | 无特殊约定 |
| 变量 | `snake_case` — `mod_count`, `external_id` | `camelCase` — `selectedMod`, `isLoading` |
| 常量 | `UPPER_SNAKE_CASE` — `BASE_URL`, `DATABASE_URL` | `UPPER_SNAKE_CASE` 或模块级 `const` — `BASE_URL` |
| 数据库字段 | `snake_case` — `first_seen_at`, `adult_content` | N/A (由后端 Schema 映射为 camelCase) |
| React Hooks | N/A | `use` 前缀 — `useUIStore`, `useQuery`, `useTranslation` |
| React 组件 Props | N/A | 接口名 `Props` 或内联 — `{ mod: ModItem; onFavorite: () => void }` |

### 模型/Schema 字段约定

- **SQLModel 模型**: 数据库字段使用 `snake_case`，必须与列名一致
- **Pydantic Schema**: 使用 `model_config = {"from_attributes": True}` 支持 ORM 模式
- **JSON 列表字段**: 数据库中以 `_json` 后缀的字符串字段存储（如 `sources_json`, `tags_json`），Schema 层负责序列化
- **前后端字段映射**: 后端 API 返回 `snake_case`，前端 TypeScript 类型使用 `camelCase`（如 `externalId` ↔ `external_id`）

## 文件组织

### Python 后端模块结构
```
backend/app/
├── main.py          # FastAPI 应用实例、CORS、路由注册、lifespan
├── config.py        # Settings 类，加载环境变量
├── db.py            # 引擎创建、init_db()、get_session() 生成器
├── models/          # SQLModel 表定义，每个模型一个文件
├── schemas/         # Pydantic 请求/响应 Schema，每个模型一个文件
├── api/             # FastAPI APIRouter 路由，每个资源一个文件
├── services/        # 业务服务类，每个服务一个文件
├── adapters/        # 外部站点适配器，继承 SourceAdapter 基类
├── jobs/            # APScheduler 任务，每个任务一个文件
└── tests/           # pytest 测试，每个模块一个文件
```

### TypeScript 前端模块结构
```
frontend/src/
├── main.tsx         # ReactDOM 入口
├── App.tsx          # RouterProvider 包装
├── index.css        # Tailwind 全局样式
├── app/             # 应用级配置 (router, queryClient, i18n)
├── pages/           # 路由页面组件 (一个文件一个页面)
├── components/      # 可复用组件
│   └── ui/          # 基础 UI 组件 (Button, Card, Drawer 等)
├── api/             # API 请求模块 (一个文件一个资源)
├── stores/          # Zustand stores
├── types/           # TypeScript 类型定义 (index.ts 集中管理)
└── locales/         # i18next JSON 翻译文件
```

### 空 `__init__.py` 约定
以下目录的 `__init__.py` 目前为空文件：
- `backend/app/adapters/__init__.py`
- `backend/app/api/__init__.py`
- `backend/app/jobs/__init__.py`
- `backend/app/models/__init__.py` (未确认)
- `backend/app/tests/__init__.py`

未来如需注册插件/适配器映射表，应在对应 `__init__.py` 中完成。

## 导入风格

### Python
- 标准库 → 第三方库 → 本地模块，按组空行分隔
- 使用绝对导入：`from app.db import get_session`
- 避免 `import *`
- 类型导入使用内置语法（Python 3.11+）：
  ```python
  from typing import Optional
  # 或
  def func(arg: str | None) -> int:
  ```

### TypeScript
- 使用 `@/` 路径别名（vite.config.ts 中配置）：
  ```typescript
  import Dashboard from "@/pages/Dashboard";
  import { useUIStore } from "@/stores/uiStore";
  import { get } from "@/api/client";
  ```
- React 导入优先：`import { useState } from "react";`
- 第三方库 → 本地模块

## 代码模式

### Python 服务模式

服务类接受 `Session` 依赖注入，方法为 `async`：

```python
class DiscoveryService:
    def __init__(self, session: Session):
        self.session = session

    async def discover_from_rule(self, rule_id: int) -> list:
        ...
```

### FastAPI 路由模式

每个路由文件定义 `router = APIRouter(prefix="/...", tags=["..."])`：

```python
from fastapi import APIRouter, Depends
from sqlmodel import Session
from app.db import get_session

router = APIRouter(prefix="/mods", tags=["mods"])

@router.get("", response_model=ModList)
async def list_mods(
    game: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    session: Session = Depends(get_session),
):
    ...
```

### Adapter 抽象模式

所有外部站点适配器继承 `SourceAdapter` 抽象基类：

```python
from abc import ABC, abstractmethod

class SourceAdapter(ABC):
    source_name: str

    @abstractmethod
    async def discover(self, rule: Any) -> list[dict]: ...

    @abstractmethod
    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> dict | None: ...
```

### TypeScript API 请求模式

所有 API 调用通过 `api/client.ts` 封装的 `get/post/put/del` 函数：

```typescript
// api/mods.ts
import { get, post } from "./client";
import type { ModItem } from "@/types";

export const fetchMods = (params?: Record<string, string>) =>
  get<ModItem[]>("/mods", params);
```

### TypeScript 组件模式

页面和组件使用函数组件 + Hooks：

```typescript
const ModCard: React.FC<{ mod: ModItem; onFavorite: (id: number) => void }> = ({
  mod,
  onFavorite,
}) => { ... };
```

### Zustand Store 模式

```typescript
export const useUIStore = create<UIState>((set) => ({
  sidebarOpen: true,
  toggleSidebar: () => set((s) => ({ sidebarOpen: !s.sidebarOpen })),
}));
```

### TanStack Query 配置

默认配置 5 分钟 stale time，失败重试 1 次：
```typescript
// app/queryClient.ts
export const queryClient = new QueryClient({
  defaultOptions: {
    queries: { staleTime: 1000 * 60 * 5, retry: 1 },
  },
});
```

### 数据库会话模式

使用生成器函数提供会话，FastAPI 依赖注入自动管理生命周期：

```python
def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
```

SQLite 特殊处理：`connect_args={"check_same_thread": False}`。

## 错误处理

### Python 后端
- 大多数服务方法目前为骨架实现（`...` 占位）
- FastAPI 自动处理 HTTP 异常
- 调度任务通过 `_run_job_with_logging()` 包装器捕获异常并记录到 `JobRun` 表

### TypeScript 前端
- API client 层统一检查 `res.ok`，非 2xx 状态抛出 `Error`
  ```typescript
  if (!res.ok) {
    throw new Error(`API Error: ${res.status} ${res.statusText}`);
  }
  ```
- TanStack Query 自动处理请求错误，配置 `retry: 1`

## 日志

- 调度器计划使用 `_run_job_with_logging()` 包装器记录任务开始/结束
- 当前处于早期阶段，日志基础设施尚未完全实现
- 未来建议使用 Python `logging` 标准库 + 结构化日志

## 测试

### 命名与位置
- 测试文件放在 `backend/app/tests/`，与源代码同目录层级
- 文件名：`test_` + 被测试模块名，如 `test_filter_service.py`
- 测试类：`Test` + 被测试类名，如 `TestFilterService`
- 测试方法：`test_` + 场景描述，如 `test_filter_by_keywords_include`

### 测试框架与模式
- **框架**: pytest + pytest-asyncio
- **Fixture 风格**: 类内 `@pytest.fixture` 方法
- **异步测试**: 所有测试方法使用 `async def`
- **测试类组织**:
  ```python
  class TestFilterService:
      @pytest.fixture
      def service(self):
          from app.services.filter_service import FilterService
          return FilterService()

      async def test_filter_by_keywords_include(self, service):
          """Mod title matches include keywords."""
          ...
  ```

### 测试覆盖范围
| 测试文件 | 覆盖模块 |
|---|---|
| `test_nexus_adapter.py` | NexusModsAdapter — 发现、详情获取、404 处理 |
| `test_loverslab_feed_adapter.py` | LoversLabFeedAdapter — Feed 解析 |
| `test_filter_service.py` | FilterService — 关键词、统计阈值、成人策略、去重 |
| `test_update_tracking.py` | UpdateTrackingService — 版本变更检测、已读标记 |

### 运行测试
```bash
cd backend
pip install -e .[dev]   # 安装 pytest, pytest-asyncio
pytest app/tests/ -v
```

## 配置与格式化

- **Python**: 使用 `pyproject.toml` 管理依赖（PEP 621），`setuptools` 构建后端
- **TypeScript**: 使用 `tsconfig.json` + 项目引用（`tsconfig.app.json`, `tsconfig.node.json`）
- **Tailwind**: `tailwind.config.js` 扫描 `./src/**/*.{js,ts,jsx,tsx}`
- **Vite**: `vite.config.ts`，配置 `@` 路径别名和 `/api` 代理
- **Linter/Formatter**: 前端有 `eslint` 脚本（`npm run lint`），后端暂无配置
- **未配置**: 后端尚无 ruff/black/mypy 配置

## Do's and Don'ts

### ✅ Do
- 使用 `snake_case` 命名 Python 文件、函数、变量
- 使用 `PascalCase` 命名 Python 类和 React 组件
- 使用 `camelCase` 命名 TypeScript 函数、变量
- 通过 `app/db.py` 的 `get_session()` 获取数据库会话
- 外部站点接入必须创建独立 SourceAdapter，不直接依赖 HTML/API 结构
- 列表字段在 SQLite 中以 `_json` 字符串存储
- API 请求通过 `api/client.ts` 封装函数发送
- 测试使用 `async def` + pytest fixture
- 环境变量通过 `app/config.py` 的 `Settings` 类统一管理
- 数组字段在代码中使用 `_json` 后缀命名（如 `sources_json`）

### ❌ Don't
- 不要在业务服务中直接解析外部站点 HTML
- 不要绕过 SourceAdapter 抽象直接调用外部 API
- 不要在 Python 中使用 `camelCase` 命名数据库字段
- 不要在 TypeScript 中使用 `snake_case` 命名属性（API 响应映射由前端自行处理）
- 不要在 SQLite 字段中直接存储 Python list/dict（必须序列化为 JSON 字符串）
- 不要硬编码 API URL 在前端组件中（使用 `client.ts` + 相对路径）
- 不要将 API 密钥写入代码或提交到仓库
