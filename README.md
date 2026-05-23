<p align="center">
  <img src="docs/mwlogo.png" alt="Mod Watcher Agent" width="160" />
</p>

<h1 align="center">Mod Watcher Agent</h1>

<p align="center">Mod 信息聚合、筛选与更新跟踪工具与 AI 智能体（面向个人、离线优先）。为非英语使用者方便发现感兴趣的 Mod。</p>

核心原则：只保存公开元数据，不下载、不镜像、不绕过权限。

<p align="center">
  <img src="docs/ModWatcherAgent.png" alt="ModWatcherAgent" width="95%" />
</p>

<p align="center">
  <img src="docs/ModWatcherAgentFavorites.png" alt="ModWatcherAgentFavorites" width="95%" />
</p>

<p align="center">
  <img src="docs/ModWatcherAgentAgent.png" alt="ModWatcherAgentAgent" width="95%" />
</p>

## 目录

- [概览](#概览)
- [你是普通用户还是开发者？](#你是普通用户还是开发者)
- [普通用户快速开始](#普通用户快速开始)
- [开发者快速开始](#开发者快速开始)
- [Docker 部署](#docker-部署)
- [常见问题与排查](#常见问题与排查)
- [配置说明（常用）](#配置说明常用)
  - [`.env` 高级设置（普通用户可忽略）](#env-高级设置普通用户可忽略)
- [功能一览](#功能一览)
- [开发与贡献](#开发与贡献)
  - [Agent 模块维护准则](#agent-模块维护准则)
  - [打包 Release](#打包-release)

## 概览

- 后端：Python 3.11+, FastAPI, SQLModel, APScheduler
- 前端：React + Vite + TypeScript + Tailwind
- 通知：Telegram / Discord；AI：多供应商 LLM 支持

## 你是普通用户还是开发者？

- 普通用户：看「[普通用户快速开始](#普通用户快速开始)」
- 开发者：看「[开发者快速开始](#开发者快速开始)」

默认端口：

- 应用（发布版前端 + API）：`http://localhost:17500`
- 前端开发服务器（Vite，仅开发者）：`http://localhost:17501`

## 普通用户快速开始

适用场景：你只想“打开就能用”，不关心源码与 Node.js。

1. 解压 Release 包（需包含 `frontend/dist`）。
2. 双击 `start-user.bat`。
3. 打开 `http://localhost:17500`，进入「设置」填写必要的 API Key 与通知配置。

常用命令：

```powershell
.\start-user.bat
.\start-user.bat /status
.\start-user.bat /stop
```

命令说明：

- `.\start-user.bat`：以**用户模式**启动应用；会自动创建 `.venv`（如不存在）并安装后端依赖，同时尝试启动系统托盘和发布版前端。
- `.\start-user.bat /status`：显示当前服务状态（如 `tray`、`backend`、`frontend`），用于确认是否已有旧实例运行或某项服务异常。
- `.\start-user.bat /stop`：停止后端、托盘与前端开发服务残留进程；在切换运行模式前建议先执行此命令以释放端口与资源。

说明：

- 若看不到托盘图标或启动异常，请检查 `log/tray.log` 和 `log/backend.log`。

## 开发者快速开始

适用场景：你要改代码、调试前端/后端、跑测试。

前置：Python 3.11+、Node.js（建议 20/22 LTS）。开发者模式会启动 Vite，Node 必须能正常执行 `child_process.spawn`。

一键启动（源码模式）：

```powershell
.\start-debug.bat
```

手动启动（后端 + 前端）示例：

```powershell
# 后端
cd backend
copy .env.example .env
python -m venv ..\.venv
..\.venv\Scripts\python -m pip install -e .[dev]
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 17500

# 前端（开发）
cd ..\frontend
npm install
npm run dev
```

从用户模式切换到开发者模式前，建议先停止旧实例：

```powershell
.\start-user.bat /stop
```

指定 Python / Node 运行时：

启动脚本会自动发现 Python 3.11+ 和可用的 Node。若机器上安装了多个版本，或默认发现结果不可用，可以通过环境变量指定：

```powershell
$env:MW_PYTHON = "C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe"
$env:MW_NODE = "C:\Program Files\nodejs\node.exe"
.\start-debug.bat
```

- `MW_PYTHON`：用于创建/校验 `.venv`，要求 Python 3.11+。
- `MW_NODE`：用于开发者模式启动 Vite，要求 Node 18+，且能正常执行 `child_process.spawn`。

## Docker 部署

Linux/macOS (bash / zsh):

```bash
cp .env.example .env
docker compose up -d
```

Windows (PowerShell):

```powershell
Copy-Item .env.example .env
docker compose up -d
```

Docker 默认：

- 应用（Nginx）：`http://localhost:17501`
- 后端 API：`http://localhost:17500`

说明：Docker Compose 使用仓库根目录 `.env`（被 `docker-compose.yml` 的 `env_file: .env` 引用）。

## 常见问题与排查

- 页面显示 `{"detail":"Not Found"}`：确认是否使用了发布版前端（`frontend/dist/index.html`），或停止旧进程后重启。
- `17501` 被占用：可能是旧的前端开发实例未停止，运行 `start.bat /stop` 后重启。
- Vite 报 `spawn EPERM`：`start-debug.bat` 会自动扫描可用 Node；如果全部失败，安装 Node 20/22 LTS，或用 `MW_NODE` 指向一个可用的 `node.exe`。

## 配置说明（常用）

- `DATABASE_URL`：默认 `sqlite:///./mod_watcher.db`（Docker 推荐 `sqlite:////app/data/mod_watcher.db`）。
- `NEXUS_API_KEY`：建议配置以启用 NexusMods 源。
- `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` / `DISCORD_WEBHOOK_URL`：外部通知。
- LLM 相关：`LLM_PROVIDER`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`。

详见 `backend/.env.example` 与设置页面。

### `.env` 高级设置（普通用户可忽略）

适用场景：你在本机源码开发、Docker 部署、或希望通过环境变量提供“默认配置”（首次启动/未在设置页保存时生效）。

文件位置：

- 本地/源码模式：后端读取 `backend/.env`（首次启动可能由 `backend/.env.example` 自动生成）
- Docker Compose：读取仓库根目录 `.env`
- 两个 `.env.example` 都是示例模板：`backend/.env.example`（本地模式）与根目录 `.env.example`（Docker）

说明：

- 普通用户：只用设置页配置即可，不需要编辑 `.env`
- 开发者：需要时直接改 `backend/.env`，并重启服务让配置生效
- 优先级：设置页保存的配置（数据库）会覆盖 `backend/.env` / 环境变量提供的默认值

## 功能一览

- 发现：从 NexusMods / LoversLab 拉取并转换为卡片。
- 规则：创建/测试/启停定期发现规则。
- 收藏：标记并跟踪 Mod 更新。
- 更新：以时间线展示版本与变更记录。
- AI：多语言摘要与介绍（按供应商优先级）。
- 通知：Telegram / Discord 推送与本地系统通知。

## 开发与贡献

- 代码风格、依赖请参阅 [DEPENDENCIES.md](./DEPENDENCIES.md) 和 [CODE_STYLE.md](./CODE_STYLE.md)。
- 欢迎贡献：fork → 新分支 → 提交 PR，并在 PR 描述中说明变更。

### Agent 模块维护准则

Agent 后端代码集中在 `backend/app/services/agent/`。修改查询、工具、结果合并或 LLM 回答生成时，请先阅读：

- [AGENETS.md](./AGENETS.md)：项目级 Agent 指令与架构边界
- [REASONIX.md](./REASONIX.md)：快速上下文与常见注意事项
- [CODE_STYLE.md](./CODE_STYLE.md)：编码规范与代码注释准则
- [Agent 模块降耦计划](./docs/superpowers/plans/2026-05-23-agent-decoupling.md)：分阶段实施方案

维护原则：

- `chat_service.py` 保持薄入口，不继续承载具体搜索工具、结果合并、排序过滤或 prompt 细节。
- Local DB、NexusMods、LoversLab 等来源检索走统一 tool 边界。
- 确定性规则用代码和测试实现，不交给 LLM 判断。
- 代码注释视为后续维护准则，只写意图、契约、不变量、安全边界和非显然兼容原因；修改逻辑时同步更新注释与测试。

### 打包 Release

在仓库根目录执行：

```powershell
.\build-release.bat
```

会在 `release/` 下生成一个包含 `frontend/dist` 的 zip 包；非开发者用户解压后直接运行 `start-user.bat` 即可。

说明：打包 Release 需要 Node.js（建议 20/22 LTS）；普通用户不需要安装 Node.js。
