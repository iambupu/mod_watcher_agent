<p align="center">
  <img src="docs/mwlogo.png" alt="Mod Watcher Agent" width="160" />
</p>

<h1 align="center">Mod Watcher Agent</h1>

<p align="center">面向个人、离线优先的 Mod 信息聚合、筛选与更新跟踪工具，并提供 AI 摘要与多语言辅助。</p>

核心原则：只保存公开元数据，不下载、不镜像 Mod 文件，不绕过站点权限。

<p align="center">
  <img src="docs/Mod%20Watcher%20Agent.png" alt="Mod Watcher Agent 界面截图" width="95%" />
</p>

> 发布状态：Windows 独立客户端、便携包、安装器和 GitHub Actions 发布链路已进入实现与本地验证阶段。请以 GitHub Release 页面实际列出的资产为准；远端 workflow、真实安装器和完整 Windows 人工矩阵的状态见 [桌面客户端验收记录](./docs/desktop-client-acceptance.md)。

## 目录

- [普通用户快速开始](#普通用户快速开始)
- [桌面客户端如何运行](#桌面客户端如何运行)
- [数据、日志与卸载](#数据日志与卸载)
- [WebView2 与浏览器要求](#webview2-与浏览器要求)
- [常见问题](#常见问题)
- [源码与开发者模式](#源码与开发者模式)
- [Docker 部署](#docker-部署)
- [配置说明](#配置说明)
- [Chrome 收藏扩展](#chrome-收藏扩展)
- [功能一览](#功能一览)
- [开发、测试与打包](#开发测试与打包)

## 普通用户快速开始

普通用户应优先使用 Windows 独立客户端，不需要安装 Python、Node.js 或 npm。

发布资产按版本命名：

| 资产 | 适用场景 |
|---|---|
| `ModWatcherAgent-Setup-<version>-win-x64.exe` | 推荐。逐用户安装，创建开始菜单快捷方式，可选桌面快捷方式。 |
| `ModWatcherAgent-<version>-win-x64-portable.zip` | 不安装。解压完整目录后运行，适合便携使用或试用。 |
| 同名 `.sha256` | 用于在运行前核对下载文件完整性。 |

### 安装版

1. 下载安装器及其同名 `.sha256`。
2. 核对 SHA256，运行安装器。
3. 从开始菜单打开 **Mod Watcher Agent**；若安装时勾选了桌面快捷方式，也可双击桌面图标。
4. 首次进入「设置」后填写所需的 Nexus、LLM 或通知配置。

安装位置固定为当前用户目录：

```text
%LOCALAPPDATA%\Programs\ModWatcherAgent
```

安装器使用逐用户模式，不要求管理员权限。

### 便携版

1. 下载便携 ZIP 及其同名 `.sha256`。
2. 把 ZIP 完整解压到普通目录，不要直接在压缩包内运行。
3. 保留 `ModWatcherAgent.exe` 与 `_internal` 的相对位置。
4. 双击 `ModWatcherAgent.exe`。

便携版只便携应用文件。数据库、日志、配置和浏览器资料仍默认写入 `%LOCALAPPDATA%\ModWatcherAgent`，不会写进解压目录。

PowerShell 校验示例：

```powershell
Get-FileHash .\ModWatcherAgent-<version>-win-x64-portable.zip -Algorithm SHA256
Get-Content .\ModWatcherAgent-<version>-win-x64-portable.zip.sha256
```

两处十六进制摘要必须一致，`.sha256` 中的文件名也必须与资产对应。

完整安装、便携使用和排障说明见 [Windows 桌面客户端指南](./docs/desktop-client.md)。

## 桌面客户端如何运行

- 双击 EXE 后，应用在同一进程中启动 FastAPI，并通过 pywebview/WebView2 显示现有 React 界面。
- 桌面后端只监听 `127.0.0.1`，默认端口为 `17500`，不默认开放到局域网。
- 点击最小化或关闭按钮时，只要系统托盘健康，窗口会隐藏而后台任务继续运行。
- 托盘双击或「打开主界面」会恢复窗口。
- 真正退出请使用托盘菜单「退出」。正常退出路径会停止托盘、后端和窗口，并释放单实例锁与端口；若进程仍在或端口未释放，请按故障路径处理。
- 若托盘初始化失败，应用不会把窗口隐藏到无法恢复的状态；此时关闭窗口会退出程序。
- 第二次启动不会创建另一套后端，而会提示从系统托盘打开已有实例。

## 数据、日志与卸载

冻结版客户端的可写数据统一位于：

```text
%LOCALAPPDATA%\ModWatcherAgent
```

常用位置：

| 内容 | 路径 |
|---|---|
| SQLite 数据库 | `data\mod_watcher.db` |
| 高级 `.env` | `config\.env` |
| 业务日志 | `logs\mod_watcher.log` |
| 桌面启动与整体生命周期日志 | `logs\desktop.log` |
| 未捕获异常 | `logs\crash.log` |
| LoversLab 浏览器资料 | `data\browser_profiles` |
| HTML 快照 | `data\snapshots` |
| WebView 状态 | `webview` |
| 迁移记录 | `backups\migration.json` |

首次启动时，如果新数据库不存在，客户端会按受控候选位置检查旧版 `mod_watcher.db`，使用 SQLite Backup API 迁移已提交数据并执行完整性检查。旧数据库不会被删除。

安装器升级不会覆盖 `%LOCALAPPDATA%\ModWatcherAgent`。卸载默认保留用户数据；只有交互卸载中连续确认两次，才会删除整个用户数据目录。静默卸载始终保留用户数据。

## WebView2 与浏览器要求

- 独立窗口要求 Microsoft Edge WebView2 Runtime，不会回退到旧版 MSHTML。
- 安装器可在构建时携带经过 Microsoft 签名验证的 Evergreen Bootstrapper；未携带或安装失败时会给出官方安装引导。直接运行 EXE 时，客户端只有在识别到 WebView2/EdgeChromium 相关启动错误后，才会在原生错误框中附上 [Microsoft WebView2 官方下载页面](https://developer.microsoft.com/microsoft-edge/webview2/)；缺失 Runtime 的真实机器路径仍待人工验收。
- LoversLab 登录和抓取优先尝试系统 Microsoft Edge 或 Google Chrome，最后回退到已经安装的 Playwright Chromium。
- 打包版不会从主 EXE 内运行 `python -m playwright install chromium`。如果 Edge 和 Chrome 都不可用，请先安装系统 Edge 或 Chrome。

## 常见问题

### 双击后没有窗口

1. 查看系统托盘，确认窗口是否已隐藏。
2. 检查 `%LOCALAPPDATA%\ModWatcherAgent\logs\desktop.log` 和 `crash.log`。
3. 安装或修复 WebView2 Runtime。
4. 检查端口 `17500` 是否被其他程序占用。

### 提示程序已在运行

这是单实例保护。请从系统托盘恢复已有窗口；若托盘中没有图标，先在任务管理器确认旧进程是否仍存在。

### LoversLab 登录窗口无法打开

确认系统 Edge 或 Chrome 可正常启动。打包版不支持在线安装 Playwright Chromium，浏览器 profile 位于 `%LOCALAPPDATA%\ModWatcherAgent\data\browser_profiles`。

### 旧数据库迁移失败

不要删除旧数据库。查看 `desktop.log`、`crash.log`，并在 `backups\migration.json` 存在时核对它；迁移失败时客户端会回滚新元数据、保留源数据库，不会用空数据库静默覆盖它。

### 安全软件提示未知应用

当前发布链尚未声明 Windows 代码签名。请先核对 GitHub Release 来源和同名 SHA256；SmartScreen、杀毒软件声誉和代码签名仍属于发布验收项。

更多处理步骤见 [桌面客户端排障章节](./docs/desktop-client.md#14-故障排查)。

## 源码与开发者模式

源码模式、Docker 和原有浏览器启动方式继续保留，但它们不是普通用户的首选桌面入口。

前置环境：

- Python 3.11+
- Node.js 18+；发布 CI 使用 Node.js 24

一键开发启动：

```powershell
.\start-debug.bat
```

传统源码用户模式仍可使用：

```powershell
.\start-user.bat
.\start-user.bat /status
.\start-user.bat /stop
```

该路径会创建 Python 虚拟环境并安装依赖，不等同于独立 EXE。开发者模式使用 Vite，默认地址为 `http://localhost:17501`；后端与发布版前端默认使用 `http://localhost:17500`。

手动启动示例：

```powershell
cd backend
Copy-Item .env.example .env
python -m venv ..\.venv
..\.venv\Scripts\python -m pip install -e ".[dev]"
..\.venv\Scripts\python -m uvicorn app.main:app --reload --port 17500

cd ..\frontend
npm install
npm run dev
```

## Docker 部署

Linux/macOS：

```bash
cp .env.example .env
docker compose up -d
```

Windows PowerShell：

```powershell
Copy-Item .env.example .env
docker compose up -d
```

Docker Compose 默认通过 `http://localhost:17501` 暴露应用，后端 API 位于 `http://localhost:17500`。Docker 和纯 FastAPI 模式不要求安装桌面 GUI 依赖。

## 配置说明

普通用户优先通过设置页面保存业务配置，包括：

- `NEXUS_API_KEY`
- `LLM_PROVIDER`、`LLM_API_KEY`、`LLM_MODEL`、`LLM_BASE_URL`
- `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`
- `DISCORD_WEBHOOK_URL`

桌面版高级配置文件位于 `%LOCALAPPDATA%\ModWatcherAgent\config\.env`。源码模式读取 `backend\.env`，Docker Compose 读取仓库根目录 `.env`。设置页保存的业务值继续覆盖环境变量提供的默认值。

API Key 和 Token 当前仍以兼容格式保存在本地 SQLite 中，尚未迁移到 Windows DPAPI 或 Credential Manager。请保护 Windows 账户和用户数据目录，不要把数据库、`.env` 或日志上传到 Issue。

## Chrome 收藏扩展

源码/传统 Release ZIP 中的 `chrome-extension\` 可在 Nexus Mods 或 LoversLab 页面把公开元数据导入本地数据库。当前桌面 onedir 与安装器契约不保证包含该目录；需要扩展时，请从源码或明确包含扩展的传统发布包加载。

安装扩展前应先启动应用并确认 `http://localhost:17500` 可访问，然后在 Chrome 的 `chrome://extensions` 中启用开发者模式并选择「加载已解压的扩展程序」。扩展不下载、不镜像 Mod 文件。

## 功能一览

- 发现：从 Nexus Mods / LoversLab 拉取并转换为卡片。
- 规则：创建、测试和启停定期发现规则。
- 收藏：标记并跟踪 Mod 更新。
- 更新：以时间线展示版本与变更记录。
- AI：多供应商、多语言摘要与介绍。
- 通知：Telegram、Discord 和本地系统通知。

## 开发、测试与打包

- 依赖与构建要求见 [DEPENDENCIES.md](./DEPENDENCIES.md)。
- Windows 桌面实现、风险和验收证据见 [桌面客户端指南](./docs/desktop-client.md) 与 [验收记录](./docs/desktop-client-acceptance.md)。
- 代码风格见 [CODE_STYLE.md](./CODE_STYLE.md)。

本地桌面构建入口：

```powershell
.\scripts\build_desktop.ps1
```

完整构建会运行测试、前端构建、PyInstaller onedir、打包 smoke、portable、安装器和 SHA256。缺少 Inno Setup 时可用 `-SkipInstaller` 只构建 onedir 与便携包。

传统源码 Release ZIP 仍使用：

```powershell
.\build-release.bat
```

商业环境使用 Inno Setup 编译安装器前，发布者必须自行核对并取得符合 [Inno Setup 当前商业许可政策](https://jrsoftware.org/isorder.php) 的许可；本仓库及其产物不提供、转让或暗示授予该许可。
