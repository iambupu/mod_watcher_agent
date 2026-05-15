# Mod Watcher Agent

Mod 信息聚合、筛选、收藏与更新跟踪工具，面向个人使用的本地 Mod 情报台。

定期从 NexusMods 和 LoversLab 发现新 Mod，根据规则过滤并展示卡片，支持收藏跟踪、AI 摘要/介绍与通知推送。

**核心原则：只保存公开元数据，不下载、不镜像、不绕过权限。**

## 技术栈

| 层 | 技术 |
|---|---|
| 后端 | Python 3.11+ · FastAPI · SQLModel · SQLite · APScheduler |
| 前端 | React 18 · Vite 5 · TypeScript · Tailwind CSS |
| 状态/请求 | TanStack Query · Zustand |
| 国际化 | react-i18next (zh-CN / en-US / ja-JP) |
| 通知 | Telegram Bot · Discord Webhook |
| 部署 | Docker Compose |

## 快速开始

### Windows 一键启动

```cmd
start.bat
```

### 本地开发启动

```bash
# 后端
cd backend
cp .env.example .env
pip install -e .[dev]
python -m uvicorn app.main:app --reload --port 7500

# 前端
cd frontend
npm install
npm run dev
```

访问地址：
- 前端（Vite Dev）：http://localhost:7501
- 后端 API：http://localhost:7500
- API 文档：http://localhost:7500/docs

### Docker 部署

```bash
docker-compose up -d
```

Docker 默认端口：
- 前端（Nginx）：http://localhost
- 后端 API：http://localhost:7500

## 环境配置

复制并编辑 `backend/.env.example`：

```bash
cd backend
cp .env.example .env
```

常用配置：

| 变量 | 必填 | 说明 |
|---|---|---|
| `DATABASE_URL` | 可选 | 数据库地址，默认 `sqlite:///./mod_watcher.db` |
| `NEXUS_API_KEY` | 推荐 | NexusMods API Key，不填会影响 Nexus 来源发现 |
| `TELEGRAM_BOT_TOKEN` | 可选 | Telegram Bot Token |
| `TELEGRAM_CHAT_ID` | 可选 | Telegram 接收 Chat ID |
| `DISCORD_WEBHOOK_URL` | 可选 | Discord Webhook |
| `OPENAI_API_KEY` | 可选 | OpenAI 兼容配置（可被设置页中的多供应商配置覆盖） |
| `LLM_PROVIDER` | 可选 | 默认 LLM 供应商：`openai/anthropic/gemini/groq/deepseek/openrouter/ollama` |
| `LLM_API_KEY` | 可选 | 默认供应商 API Key |
| `LLM_MODEL` | 可选 | 默认模型名 |
| `LLM_BASE_URL` | 可选 | OpenAI 兼容 Base URL |
| `CORS_ORIGINS` | 可选 | 逗号分隔，默认 `http://localhost:5173,http://127.0.0.1:5173`（当前前端开发端口为 `7501`，浏览器直连后端时请按实际端口调整） |
| `LOCAL_ONLY_API` | 可选 | 默认 `true`，仅允许本机访问 `/api/*` |

## 功能概览

- 发现：按规则从 NexusMods/LoversLab 拉取并过滤新 Mod
- 规则：支持创建、编辑、测试、启停与手动运行规则
- 收藏：收藏 Mod 并跟踪更新
- 更新：查看更新事件流并管理已读状态
- AI：生成多语言摘要与详细介绍（按设置的供应商和优先级）
- 通知：Telegram/Discord 推送测试与发送记录
- 调度：内置任务调度，支持手动触发与状态查看
- 设置：支持 API Key、多 LLM 供应商优先级、代理、自动启动、配置导入导出

## 页面与路由

| 页面 | 路由 | 功能 |
|---|---|---|
| 首页 | `/` | 统计总览 |
| 发现 | `/discover` | 浏览与筛选 Mod |
| 收藏 | `/favorites` | 收藏管理与跟踪 |
| 更新 | `/updates` | 更新事件时间线 |
| 规则列表 | `/rules` | 规则列表、启停、手动运行 |
| 新建规则 | `/rules/new` | 新建规则 |
| 编辑规则 | `/rules/:id/edit` | 编辑规则 |
| 日志 | `/logs` | 通知/任务相关日志视图 |
| 设置 | `/settings` | 应用与集成配置 |

## 主要 API 前缀

- `/api/mods`
- `/api/rules`
- `/api/favorites`
- `/api/updates`
- `/api/settings`
- `/api/jobs`
- `/api/logs`
- `/api/system-notifications`

## 数据源

| 数据源 | 方式 | 需要 Key |
|---|---|---|
| NexusMods | API 拉取 | 推荐配置 |
| LoversLab | RSS + 页面抓取 | 否 |

## 文档

| 文档 | 内容 |
|---|---|
| [ARCHITECTURE.md](./docs/ARCHITECTURE.md) | 架构、数据流、组件设计 |
| [DEPENDENCIES.md](./DEPENDENCIES.md) | 后端/前端依赖清单与安装方式 |
| [CODE_STYLE.md](./CODE_STYLE.md) | 代码风格与规范 |
| [AGENETS.md](./AGENETS.md) | Agent 协作说明 |
| [docs/api-contract.md](./docs/api-contract.md) | REST API 合约 |
| [docs/source-adapters.md](./docs/source-adapters.md) | 数据源适配器设计 |
| [docs/nexusmods-integration.md](./docs/nexusmods-integration.md) | NexusMods 接入细节 |
| [docs/loverslab-integration.md](./docs/loverslab-integration.md) | LoversLab 接入细节 |
| [docs/deployment.md](./docs/deployment.md) | 部署说明 |
