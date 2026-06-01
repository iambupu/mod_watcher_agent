<p align="center">
  <img src="docs/mwlogo.png" alt="Mod Watcher Agent" width="160" />
</p>

<h1 align="center">Mod Watcher Agent</h1>

<p align="center">Mod 信息聚合、筛选与更新跟踪工具与 AI 智能体（面向个人、离线优先）。为非英语使用者方便发现感兴趣的 Mod。</p>

核心原则：只保存公开元数据，不下载、不镜像、不绕过权限。

<p align="center">
  <img src="docs/Mod%20Watcher%20Agent.png" alt="Mod Watcher Agent 界面截图" width="95%" />
</p>

## 目录

- [目录](#目录)
- [概览](#概览)
- [你是普通用户还是开发者？](#你是普通用户还是开发者)
- [普通用户快速开始](#普通用户快速开始)
- [开发者快速开始](#开发者快速开始)
- [Docker 部署](#docker-部署)
- [常见问题与排查](#常见问题与排查)
- [配置说明（常用）](#配置说明常用)
  - [`.env` 高级设置（普通用户可忽略）](#env-高级设置普通用户可忽略)
- [Chrome 收藏扩展](#chrome-收藏扩展)
- [功能一览](#功能一览)
- [开发与贡献](#开发与贡献)
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

- `DATABASE_URL`：默认 `sqlite:///./backend/mod_watcher.db`（Docker 推荐 `sqlite:////app/data/mod_watcher.db`）。
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

## Chrome 收藏扩展

Release 包会包含 `chrome-extension/`。它用于在 Nexus Mods 或 LoversLab 的 Mod 页面一键导入到本地数据库并加入收藏。

安装：

1. 先运行 `.\start-user.bat`，确认 `http://localhost:17500` 可打开。
2. 打开 Chrome 的 `chrome://extensions`。
3. 启用「开发者模式」。
4. 点击「加载已解压的扩展程序」，选择 Release 包内的 `chrome-extension` 文件夹。

使用：

1. 打开支持的 Mod 页面：`https://www.nexusmods.com/{game_domain}/mods/{mod_id}` 或 `https://www.loverslab.com/files/file/{file_id}-...`。
2. 点击扩展图标，确认游戏名、成人内容标记和可选备注。
3. 点击「收藏当前 Mod」。

如果设置页选择了 `local_strict` 或 `shared_lan` 访问配置，需要在扩展中填写 `MW_ADMIN_TOKEN`。扩展只保存页面公开元数据，不下载、不镜像 Mod 文件。

## 功能一览

- 发现：从 NexusMods / LoversLab 拉取并转换为卡片。
- 规则：创建/测试/启停定期发现规则。
- 收藏：标记并跟踪 Mod 更新。
- 更新：以时间线展示版本与变更记录。
- AI：多语言摘要与介绍（按供应商优先级）。
- 通知：Telegram / Discord 推送与本地系统通知。

## 开发与贡献

- 代码风格、依赖请参阅 [DEPENDENCIES.md](./DEPENDENCIES.md) 和 [CODE_STYLE.md](./CODE_STYLE.md)。
- 项目文档入口请参阅 [docs/agent-technical-implementation.md](./docs/agent-technical-implementation.md)，其中包含 Agent 当前实现链路与检索排障入口。
- 欢迎贡献：fork → 新分支 → 提交 PR，并在 PR 描述中说明变更。

### 打包 Release

在仓库根目录执行：

```powershell
.\build-release.bat
```

会在 `release/` 下生成一个包含 `frontend/dist` 的 zip 包；非开发者用户解压后直接运行 `start-user.bat` 即可。

说明：打包 Release 需要 Node.js（建议 20/22 LTS）；普通用户不需要安装 Node.js。
