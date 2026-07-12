# Mod Watcher Agent Windows 独立客户端技术设计

> - 文档状态：已实施；远端发布与 Windows GUI/人工矩阵待验收
> - 目标仓库：`iambupu/mod_watcher_agent`
> - 基线版本：`0.2.2`
> - 目标平台：Windows 10/11 x64
> - 客户端形态：独立原生窗口 + 系统托盘 + 最小化/关闭到托盘
> - 推荐技术：FastAPI + React/Vite + pywebview + pystray + PyInstaller（onedir）

---

## 1. 文档目的

本文定义 Mod Watcher Agent 从“源码/Release ZIP + Python 虚拟环境 + 浏览器页面”升级为 Windows 独立桌面客户端的完整技术方案。

最终用户应能够：

1. 下载安装包或便携版压缩包。
2. 无需安装 Python、Node.js、npm。
3. 双击 `ModWatcherAgent.exe` 打开独立桌面窗口。
4. 最小化或关闭窗口后，程序继续在系统托盘运行。
5. 从托盘恢复窗口或真正退出。
6. 保留现有数据库、设置、定时任务、AI 能力、通知能力和 LoversLab 浏览器能力。
7. 升级客户端时不覆盖用户数据库、配置、日志和浏览器登录状态。

本文只定义 Windows 客户端。Linux、macOS、移动端和 Microsoft Store 打包不在当前范围。

---

## 2. 当前系统基线

### 2.1 当前技术栈

后端：

- Python 3.11+
- FastAPI
- Uvicorn
- SQLModel / SQLAlchemy
- SQLite
- Alembic
- APScheduler
- HTTPX
- Playwright
- LangGraph
- pystray
- Pillow

前端：

- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router
- TanStack Query
- Zustand
- i18next

### 2.2 当前生产运行方式

当前发布版已将 React 构建结果放在 `frontend/dist`，由 FastAPI 托管静态资源与 SPA fallback。生产运行不需要 Vite 开发服务器。

当前普通用户流程大致为：

```text
start-user.bat
  -> start.ps1
  -> 检测/安装 Python
  -> 创建 .venv
  -> 安装 backend 依赖
  -> 检测 frontend/dist
  -> 启动 backend/tray_app.py
  -> tray_app.py 创建 uvicorn 子进程
  -> 默认浏览器访问 http://127.0.0.1:17500
```

这已经具备发布版前后端合并、托盘、单实例检查、日志和后台调度能力，但仍有以下问题：

- 用户必须具备或临时安装 Python 3.11+。
- 第一次启动需要在线安装 Python 依赖。
- 启动入口依赖 BAT 和 PowerShell。
- 用户界面运行在默认浏览器中，不是独立桌面窗口。
- 数据库和日志路径与源码/解压目录绑定。
- 当前 `tray_app.py` 使用 `sys.executable -m uvicorn` 创建子进程，不适合直接冻结成 EXE。
- Playwright Chromium 安装逻辑同样依赖 `sys.executable -m playwright`。
- 安装在受保护目录时可能出现数据库和日志写权限问题。

---

## 3. 目标与非目标

## 3.1 功能目标

### 必须实现

- 独立 Windows 原生窗口。
- 系统托盘常驻。
- 窗口最小化到托盘。
- 点击窗口关闭按钮时隐藏到托盘，而不是退出。
- 托盘双击或“打开主界面”恢复窗口。
- 托盘“退出”执行完整关闭。
- FastAPI 服务内嵌启动。
- React 静态资源随 EXE 分发。
- 用户无需 Python 和 Node.js。
- 数据写入 `%LOCALAPPDATA%\ModWatcherAgent`。
- 支持现有 SQLite 数据迁移。
- 支持便携 ZIP 和安装包。
- GitHub Actions 自动构建 Windows 产物。
- 保留源码开发启动方式。

### 应当实现

- 启动失败时给出可理解的原生错误提示。
- 崩溃后日志可用于排障。
- WebView2 缺失时显示安装提示。
- 第二次启动时不创建第二套后端。
- 更新或卸载不自动删除用户数据。
- 保持当前本地访问安全策略。

## 3.2 非目标

当前阶段不实现：

- Electron。
- Tauri/Rust 重写。
- 原生 WinUI/WPF 重写 React 界面。
- 内置自动更新器。
- Microsoft Store/MSIX。
- macOS/Linux 客户端。
- 云端账号同步。
- 后台 Windows Service。
- 强制打包 Playwright Chromium。
- 将 API Key 加密迁移到 Windows Credential Manager。
- 修改核心 Mod 聚合、AI、通知和规则业务逻辑。

---

## 4. 技术选型

## 4.1 推荐方案

采用：

```text
PyInstaller onedir
+ pywebview
+ FastAPI/Uvicorn 进程内运行
+ pystray
+ React 静态前端
```

### 选择理由

1. 后端主体已经是 Python，不需要引入第二套桌面运行时。
2. 前端已经是可静态构建的 React SPA。
3. FastAPI 已经托管生产前端。
4. 已有 pystray 托盘逻辑可复用。
5. pywebview 可复用系统 WebView2，不需要打包完整 Chromium。
6. PyInstaller 可以把 Python 解释器、后端模块和静态资源一起打包。
7. onedir 比 onefile 更适合包含大量 Python 模块、静态资源和浏览器相关依赖的应用。

## 4.2 不选 Electron

Electron 会带来：

- 第二套 Node 主进程架构。
- 更大的安装体积。
- Python 后端仍需单独打包和管理。
- IPC、进程生命周期、签名和升级链路更复杂。
- 现有 pystray 和启动器逻辑难以直接复用。

## 4.3 不选 Tauri

Tauri 体积更小，但需要：

- Rust 工具链。
- Python sidecar 管理。
- 新增 Rust/JavaScript IPC。
- 重新实现托盘和进程控制。
- 提高维护门槛。

对于当前 Python 主导的项目，收益不足以抵消改造成本。

## 4.4 选择 onedir 而不是 onefile

发布目录：

```text
ModWatcherAgent/
├─ ModWatcherAgent.exe
├─ _internal/
├─ chrome-extension/
├─ README.txt
└─ LICENSE
```

选择 onedir 的理由：

- 启动时不需要把全部内容解压到临时目录。
- 静态资源、Alembic 脚本和依赖 DLL 路径更可控。
- 启动速度更稳定。
- 更容易排查漏包和 hidden import。
- 更适合 Playwright、pywebview、Pillow、SQLAlchemy 等依赖。
- 安装包仍然可以让用户只接触一个快捷方式。

onefile 可以作为后续实验性 portable 版本，但不作为首发主方案。

---

## 5. 总体架构

```text
┌──────────────────────────────────────────────────────────┐
│                    ModWatcherAgent.exe                    │
│                                                          │
│  ┌──────────────── Desktop Application ────────────────┐ │
│  │ SingleInstanceGuard                                 │ │
│  │ RuntimePaths                                        │ │
│  │ DesktopController                                   │ │
│  │                                                     │ │
│  │ ┌───────────────┐    ┌───────────────────────────┐ │ │
│  │ │ pywebview UI  │    │ pystray System Tray       │ │ │
│  │ │ Main Thread   │    │ Tray Worker Thread        │ │ │
│  │ └───────┬───────┘    └─────────────┬─────────────┘ │ │
│  │         │                           │               │ │
│  │         └──────── DesktopController ┘               │ │
│  │                         │                           │ │
│  │             ┌───────────▼───────────┐               │ │
│  │             │ Embedded Uvicorn      │               │ │
│  │             │ Background Thread     │               │ │
│  │             └───────────┬───────────┘               │ │
│  └─────────────────────────┼────────────────────────────┘ │
│                            │ http://127.0.0.1:17500       │
│  ┌─────────────────────────▼────────────────────────────┐ │
│  │ FastAPI                                             │ │
│  │ API + Scheduler + SQLite + React frontend/dist      │ │
│  └─────────────────────────┬────────────────────────────┘ │
└────────────────────────────┼──────────────────────────────┘
                             │
          %LOCALAPPDATA%\ModWatcherAgent\
```

---

## 6. 进程与线程模型

## 6.1 单进程设计

发布版只启动一个主进程：

```text
ModWatcherAgent.exe
```

主进程内部包括：

- 主线程：pywebview GUI 消息循环。
- Uvicorn 后台线程：FastAPI 服务。
- pystray 托盘线程。
- APScheduler 自身工作线程。
- 网络请求和业务线程。
- 必要时启动系统 Edge/Chrome/Playwright 浏览器子进程。

不再为 FastAPI 创建单独 Python 子进程。

## 6.2 为什么必须进程内启动 FastAPI

PyInstaller 冻结后：

```python
sys.executable
```

指向的是：

```text
ModWatcherAgent.exe
```

而不是 `python.exe`。

因此以下现有逻辑不能保留在发布模式：

```python
subprocess.Popen([
    sys.executable,
    "-m",
    "uvicorn",
    "app.main:app",
])
```

否则可能重新执行桌面 EXE、进入递归启动、参数无法识别，或者无法按预期执行 Uvicorn 模块。

正确方式是直接导入应用：

```python
from app.main import app
import uvicorn

config = uvicorn.Config(
    app=app,
    host="127.0.0.1",
    port=17500,
    log_config=None,
    access_log=False,
)
server = uvicorn.Server(config)
server.run()
```

## 6.3 线程职责

### 主线程

只负责：

- 创建 pywebview Window。
- 运行 `webview.start()`。
- 处理原生窗口生命周期。

pywebview 的 GUI 循环必须位于主线程。

### Uvicorn 线程

职责：

- 运行 FastAPI。
- 初始化数据库和迁移。
- 初始化设置。
- 启动 APScheduler。
- 托管 React 静态文件。
- 提供 API。

线程属性：

```python
daemon=False
```

退出时由 DesktopController 显式设置 `server.should_exit = True` 并等待结束。

### 托盘线程

职责：

- 创建系统托盘图标。
- 接收“显示窗口”“检查更新”“退出”等操作。
- 不直接修改复杂业务状态。
- 通过 DesktopController 调度窗口和服务操作。

---

## 7. 桌面生命周期状态机

定义状态：

```text
CREATED
STARTING_BACKEND
BACKEND_READY
WINDOW_VISIBLE
WINDOW_HIDDEN
EXITING
STOPPED
FAILED
```

状态流：

```text
CREATED
  -> STARTING_BACKEND
  -> BACKEND_READY
  -> WINDOW_VISIBLE
  -> WINDOW_HIDDEN
  -> WINDOW_VISIBLE
  -> EXITING
  -> STOPPED
```

异常流：

```text
STARTING_BACKEND -> FAILED
BACKEND_READY    -> FAILED
WINDOW_VISIBLE   -> FAILED
```

## 7.1 启动流程

1. 初始化基础日志。
2. 解析运行模式。
3. 创建用户数据目录。
4. 获取单实例锁。
5. 执行旧数据迁移检测。
6. 设置运行时环境变量。
7. 创建 Uvicorn Server。
8. 后台线程启动 FastAPI。
9. 轮询 `/api/health` 或 TCP 端口。
10. 后端就绪后创建 pywebview 窗口。
11. 创建托盘。
12. 进入 GUI 主循环。
13. 页面加载 `http://127.0.0.1:17500`。

## 7.2 后端启动超时

默认：

```text
30 秒
```

超时后：

- 写入错误日志。
- 显示原生错误对话框。
- 提供日志目录位置。
- 终止托盘。
- 停止残留 Uvicorn。
- 释放单实例锁。
- 返回非零退出码。

不应出现空白 WebView 无限等待。

---

## 8. 原生窗口设计

## 8.1 窗口参数

建议默认值：

```python
webview.create_window(
    title="Mod Watcher Agent",
    url="http://127.0.0.1:17500",
    width=1440,
    height=900,
    min_size=(1024, 700),
    resizable=True,
    confirm_close=False,
    background_color="#0b1220",
)
```

首版使用系统原生标题栏，不使用 frameless 自绘标题栏。

理由：

- 系统最小化、最大化和 DPI 行为更稳定。
- 无需重新实现窗口拖动、缩放和系统菜单。
- 减少多显示器和高 DPI 缺陷。
- 更符合“最小改造”目标。

## 8.2 WebView2

Windows 下优先使用 Edge Chromium/WebView2。

应用启动时应检查 WebView2 可用性。不可用时：

- 不退回旧版 MSHTML。
- 显示“需要 Microsoft Edge WebView2 Runtime”的原生提示。
- 安装包可携带 Evergreen Bootstrapper。
- 用户取消安装时安全退出。

## 8.3 WebView 数据目录

WebView 本地存储目录：

```text
%LOCALAPPDATA%\ModWatcherAgent\webview
```

启动参数：

```python
webview.start(
    private_mode=False,
    storage_path=str(paths.webview_dir),
)
```

这样可保留：

- LocalStorage。
- Cookie。
- 前端偏好。
- WebView 会话数据。

业务配置仍以后端 SQLite 为主，WebView 存储不能成为关键配置的唯一来源。

## 8.4 外部链接

应用内业务页面保持在 WebView 中。

外部站点链接应在系统浏览器打开，包括：

- Nexus Mods。
- LoversLab。
- GitHub。
- 文档站点。
- 第三方授权页面。

建议启用：

```python
webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
```

---

## 9. 最小化和关闭到托盘

## 9.1 行为定义

### 点击最小化按钮

```text
窗口隐藏
程序继续运行
托盘继续显示
定时任务继续执行
```

### 点击关闭按钮

默认行为同最小化：

```text
取消真正关闭
隐藏窗口
显示一次托盘提示
```

### 托盘“退出”

执行真正关闭：

```text
停止新任务
停止调度器
关闭登录浏览器 context
停止 Uvicorn
销毁 WebView
移除托盘
释放锁
退出进程
```

## 9.2 pywebview 事件绑定

设计：

```python
window.events.minimized += on_minimized
window.events.closing += on_closing
```

处理逻辑：

```python
def on_minimized():
    if not controller.is_exiting:
        window.hide()

def on_closing():
    if controller.is_exiting:
        return True
    window.hide()
    controller.notify_minimized_to_tray_once()
    return False
```

`closing` 返回 `False`，取消关闭操作。

## 9.3 恢复窗口

托盘操作：

```python
def show_window():
    window.show()
    window.restore()
```

必要时通过原生窗口句柄执行置前操作，防止恢复后窗口仍在其他窗口后面。

## 9.4 首次提示

第一次点击关闭时显示系统通知：

```text
Mod Watcher Agent 仍在后台运行。
可通过系统托盘重新打开或退出。
```

提示状态可写入 SQLite 设置：

```text
desktop_tray_hint_shown=true
```

以后不重复提示。

---

## 10. 系统托盘设计

## 10.1 托盘菜单

```text
打开主界面
────────────────
立即检查新 Mod
检查收藏更新
────────────────
暂停/恢复定时任务
打开日志目录
────────────────
退出
```

开发模式可增加：

```text
打开 API 文档
```

生产模式默认不突出 API 文档入口。

## 10.2 图标行为

- 单击：可不做处理，避免平台差异。
- 双击：恢复主窗口。
- 右键：打开菜单。
- 主窗口隐藏后托盘必须继续存在。
- 托盘创建失败时，关闭按钮应恢复为真正退出，避免应用进入不可恢复的隐藏状态。

## 10.3 托盘失败降级

如果 pystray 初始化失败：

```text
tray_available = false
```

行为调整：

- 最小化保留普通最小化，不自动隐藏。
- 关闭按钮真正退出。
- 在日志中记录降级原因。
- 应用仍可使用。

---

## 11. 单实例策略

## 11.1 第一阶段

复用现有 Windows Named Mutex：

```text
Local\ModWatcherAgentDesktop
```

启动时：

- 成功取得 Mutex：继续启动。
- Mutex 已存在：显示“程序已在运行，请从系统托盘打开”，然后退出。

## 11.2 后续增强

可增加第二实例唤醒协议：

```text
\\.\pipe\ModWatcherAgentDesktop
```

第二个 EXE 向已有进程发送：

```json
{"command":"show"}
```

已有进程收到后恢复窗口。

该功能不阻塞首版发布。

## 11.3 不使用端口作为唯一单实例判断

仅检查 `17500` 端口不可靠：

- 端口可能被其他程序占用。
- 后端可能启动但桌面窗口未创建。
- 用户可能修改后端端口。
- 无法区分旧源码版和新客户端。

Mutex 是权威单实例信号，端口仅用于后端健康检测。

---

## 12. 运行时路径设计

新增：

```text
backend/app/runtime_paths.py
```

## 12.1 路径类别

### Bundle 资源目录：只读

包含：

- Python 模块。
- `frontend/dist`。
- Alembic 配置和版本脚本。
- 图标。
- 默认配置模板。
- 应用元数据。

### 用户数据目录：可写

```text
%LOCALAPPDATA%\ModWatcherAgent\
├─ data\
│  ├─ mod_watcher.db
│  ├─ mod_watcher.db-wal
│  ├─ mod_watcher.db-shm
│  ├─ snapshots\
│  └─ browser_profiles\
├─ config\
│  └─ .env
├─ logs\
├─ cache\
├─ webview\
├─ runtime\
└─ backups\
```

## 12.2 RuntimePaths 接口

```python
@dataclass(frozen=True)
class RuntimePaths:
    bundle_root: Path
    executable_dir: Path
    user_root: Path
    data_dir: Path
    config_dir: Path
    log_dir: Path
    cache_dir: Path
    webview_dir: Path
    runtime_dir: Path
    backup_dir: Path
    database_path: Path
    frontend_dist_dir: Path
    alembic_ini_path: Path
```

主要函数：

```python
def is_frozen() -> bool
def get_bundle_root() -> Path
def get_executable_dir() -> Path
def get_user_root() -> Path
def build_runtime_paths() -> RuntimePaths
def ensure_runtime_directories(paths: RuntimePaths) -> None
```

## 12.3 开发模式路径

源码运行时保留当前开发体验：

```text
数据库：backend/mod_watcher.db
日志：log/
静态前端：frontend/dist/
浏览器 profile：backend/data/browser_profiles/
```

允许通过：

```text
MW_USER_DATA_DIR
```

覆盖用户目录，用于测试。

## 12.4 发布模式路径

冻结运行时默认：

```text
MW_USER_DATA_DIR=%LOCALAPPDATA%\ModWatcherAgent
DATABASE_URL=sqlite:///<LOCALAPPDATA path>/data/mod_watcher.db
LOG_DIR=<LOCALAPPDATA path>/logs
MW_BROWSER_PROFILE_ROOT=<LOCALAPPDATA path>/data/browser_profiles
MW_SNAPSHOT_ROOT=<LOCALAPPDATA path>/data/snapshots
```

所有环境变量必须在导入 `app.config`、`app.db` 和 `app.main` 前设置，因为当前 Settings 和 SQLAlchemy Engine 在模块导入阶段初始化。

---

## 13. 配置加载与优先级

建议优先级：

```text
命令行参数
> 桌面启动器注入的运行时环境变量
> 用户 config/.env
> 数据库设置
> 应用默认值
```

但现有业务中“设置页持久化值覆盖环境默认值”的语义应保持。

更准确地分层：

### 基础运行时配置

只能由启动器/环境配置：

- 用户数据目录。
- 数据库 URL。
- 日志目录。
- 绑定地址。
- 端口。
- 静态资源路径。

### 业务配置

优先从数据库读取：

- Nexus API Key。
- LLM 供应商。
- LLM API Key。
- Telegram。
- Discord。
- 规则间隔。
- 语言。
- 通知。
- 代理。
- 成人内容策略。

## 13.1 .env 文件

发布模式文件：

```text
%LOCALAPPDATA%\ModWatcherAgent\config\.env
```

用途：

- 高级启动配置。
- 诊断和临时覆盖。
- 不要求普通用户编辑。

首次启动可从内置 `.env.example` 复制。

---

## 14. 数据库迁移

## 14.1 新数据库位置

```text
%LOCALAPPDATA%\ModWatcherAgent\data\mod_watcher.db
```

## 14.2 旧数据库候选位置

首版检测：

```text
<exe_dir>\backend\mod_watcher.db
<exe_dir>\mod_watcher.db
<current_working_directory>\backend\mod_watcher.db
```

只在新数据库不存在时执行迁移。

## 14.3 迁移方法

禁止简单复制正在使用的 SQLite 文件。

推荐使用 SQLite Backup API：

```python
source = sqlite3.connect(legacy_path)
target = sqlite3.connect(new_path)
source.backup(target)
target.close()
source.close()
```

迁移完成后：

1. 计算源文件大小和目标文件大小。
2. 执行 `PRAGMA integrity_check`。
3. 把迁移记录写入日志。
4. 不删除源数据库。
5. 将源数据库位置记录到：

```text
%LOCALAPPDATA%\ModWatcherAgent\backups\migration.json
```

然后由现有 `init_db()` 执行 Alembic 和轻量迁移。

## 14.4 数据回滚

如果迁移失败：

- 删除未完成的新数据库。
- 保留旧数据库。
- 客户端显示错误。
- 不启动空数据库覆盖用户体验。
- 用户可查看迁移日志。

---

## 15. FastAPI 与静态前端

## 15.1 静态资源路径

现有代码通过相对源码目录查找：

```text
frontend/dist
```

需要改为：

```python
FRONTEND_DIST_DIR = runtime_paths.frontend_dist_dir
```

开发模式和冻结模式由 RuntimePaths 统一处理。

## 15.2 健康检查

新增：

```http
GET /api/health
```

返回：

```json
{
  "status": "ok",
  "version": "0.2.2",
  "database": "ready",
  "scheduler": "running",
  "frontend": "ready",
  "desktop": true
}
```

桌面启动器只在健康检查通过后加载主页面。

## 15.3 桌面环境标识

启动器注入：

```text
MW_DESKTOP_MODE=true
```

健康接口和前端系统信息接口可以返回：

```json
{
  "desktopMode": true,
  "packaged": true
}
```

前端据此隐藏不适用于桌面版的提示，例如“请运行 start-user.bat”。

## 15.4 绑定地址

桌面版强制：

```text
127.0.0.1
```

不允许设置为：

```text
0.0.0.0
```

LAN 共享继续作为源码/Docker 模式能力，不由独立桌面客户端默认启用。

---

## 16. Playwright 和 LoversLab 浏览器能力

## 16.1 当前问题

现有 Chromium 安装逻辑：

```python
[sys.executable, "-m", "playwright", "install", "chromium"]
```

冻结后 `sys.executable` 是主 EXE，因此该命令不可直接使用。

## 16.2 首版策略

保留当前浏览器选择顺序：

```text
系统 Microsoft Edge
-> 系统 Google Chrome
-> Playwright Chromium
```

Windows 通常已经安装 Edge，因此首版不强制随客户端打包 Playwright Chromium。

优点：

- 大幅减小安装包。
- 不重复分发浏览器。
- 可继续使用持久化登录 profile。
- 系统浏览器具有正常更新机制。

## 16.3 Chromium 可选安装

首版可采用以下两种方式之一。

### 推荐：独立浏览器安装辅助程序

构建时保留一个真实 Python/Playwright 驱动并不经济，因此推荐改为：

- UI 默认提示使用系统 Edge。
- 系统 Edge/Chrome 均不可用时，提示用户安装 Edge。
- 暂时禁用 EXE 内的“安装 Playwright Chromium”按钮。

### 后续：下载预打包 Chromium

后续可以提供单独浏览器包：

```text
ModWatcherAgent-BrowserRuntime.zip
```

下载到：

```text
%LOCALAPPDATA%\ModWatcherAgent\browsers
```

并设置：

```text
PLAYWRIGHT_BROWSERS_PATH
```

该方案需要增加版本清单、SHA256 校验和升级策略。

## 16.4 浏览器 profile 路径

当前相对路径：

```text
data/browser_profiles
```

改为：

```text
%LOCALAPPDATA%\ModWatcherAgent\data\browser_profiles
```

HTML 快照路径改为：

```text
%LOCALAPPDATA%\ModWatcherAgent\data\snapshots\loverslab
```

---

## 17. 应用退出与资源清理

退出顺序必须固定：

1. 设置 `is_exiting = True`。
2. 禁止新的托盘任务。
3. 停止或暂停 APScheduler。
4. 关闭 Playwright 登录 context。
5. 设置 `uvicorn_server.should_exit = True`。
6. 等待 Uvicorn 线程，默认最多 10 秒。
7. 超时则记录强制退出。
8. 停止 pystray Icon。
9. 销毁 WebView Window。
10. 删除运行锁文件。
11. 释放 Named Mutex。
12. 退出进程。

退出逻辑必须幂等：

```python
if self._exit_started.is_set():
    return
```

托盘退出、异常处理和系统关闭都调用同一个 `shutdown()`。

---

## 18. 建议的代码结构

```text
backend/
├─ desktop_app.py
├─ tray_app.py
└─ app/
   ├─ runtime_paths.py
   ├─ main.py
   ├─ config.py
   ├─ db.py
   ├─ logger.py
   ├─ desktop/
   │  ├─ __init__.py
   │  ├─ controller.py
   │  ├─ backend_server.py
   │  ├─ single_instance.py
   │  ├─ tray.py
   │  ├─ window.py
   │  ├─ startup.py
   │  └─ errors.py
   └─ services/
      └─ browser/
         └─ page_fetcher.py

packaging/
├─ mod_watcher_agent.spec
├─ version_info.txt
├─ hooks/
│  ├─ hook-sqlmodel.py
│  ├─ hook-playwright.py
│  └─ hook-pywebview.py
├─ installer/
│  └─ ModWatcherAgent.iss
└─ assets/
   ├─ app.ico
   └─ installer-wizard.bmp

scripts/
├─ build_desktop.ps1
├─ smoke_test_desktop.ps1
└─ package_portable.ps1

.github/workflows/
└─ desktop-release.yml
```

## 18.1 tray_app.py 处理策略

不建议继续把 `tray_app.py` 作为所有桌面逻辑的巨型文件。

应拆出可复用组件：

```text
app.desktop.tray
app.desktop.single_instance
app.desktop.controller
```

然后：

- `desktop_app.py`：EXE 入口。
- `tray_app.py`：保留源码浏览器模式和诊断 CLI。
- 两者复用相同的托盘和单实例组件。

---

## 19. 核心接口设计

## 19.1 EmbeddedBackendServer

```python
class EmbeddedBackendServer:
    def __init__(self, host: str, port: int) -> None: ...
    def start(self) -> None: ...
    def wait_ready(self, timeout: float) -> bool: ...
    def stop(self, timeout: float = 10.0) -> None: ...
    @property
    def error(self) -> Exception | None: ...
```

约束：

- 只能启动一次。
- `stop()` 可重复调用。
- 启动线程异常必须回传给 DesktopController。
- 就绪检查使用健康接口，而不仅是 TCP 端口。

## 19.2 DesktopController

```python
class DesktopController:
    def start(self) -> int: ...
    def show_window(self) -> None: ...
    def hide_window(self) -> None: ...
    def toggle_window(self) -> None: ...
    def shutdown(self, reason: str) -> None: ...
    def open_log_directory(self) -> None: ...
```

它是窗口、托盘和后端之间唯一协调者。

## 19.3 TrayController

```python
class TrayController:
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def notify(self, title: str, message: str) -> None: ...
```

TrayController 不直接操作数据库，不直接启动 Uvicorn。

## 19.4 SingleInstanceGuard

```python
class SingleInstanceGuard:
    def acquire(self) -> bool: ...
    def release(self) -> None: ...
```

Windows 使用 Named Mutex；测试环境可使用文件锁替代。

---

## 20. PyInstaller 打包设计

## 20.1 入口

```text
backend/desktop_app.py
```

## 20.2 Spec 基本结构

```python
a = Analysis(
    ["backend/desktop_app.py"],
    pathex=["backend"],
    datas=[
        ("frontend/dist", "frontend/dist"),
        ("backend/alembic.ini", "backend"),
        ("backend/alembic", "backend/alembic"),
        ("backend/.env.example", "backend"),
        ("docs/mwlogo.png", "assets"),
        ("packaging/assets/app.ico", "assets"),
    ],
    hiddenimports=[
        "uvicorn.logging",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan.on",
        "sqlalchemy.dialects.sqlite",
        "alembic",
        "pystray._win32",
        "webview.platforms.edgechromium",
    ],
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "cefpython3",
        "tkinter",
    ],
)
```

实际 hidden import 应以构建日志和 smoke test 为准，不应仅依赖静态列表。

## 20.3 数据文件

必须包含：

- `frontend/dist/index.html`
- `frontend/dist/assets/**`
- `backend/alembic.ini`
- `backend/alembic/versions/**`
- `.env.example`
- 应用图标
- 必要的包数据和证书文件

## 20.4 Windows EXE 选项

```python
EXE(
    ...,
    name="ModWatcherAgent",
    console=False,
    icon="packaging/assets/app.ico",
    version="packaging/version_info.txt",
    uac_admin=False,
)
```

不得要求管理员权限。

## 20.5 调试构建

提供：

```text
ModWatcherAgent.Debug.exe
```

或构建开关：

```powershell
.\scripts\build_desktop.ps1 -Debug
```

调试版：

- `console=True`
- pywebview debug 可选开启
- Uvicorn access log 可开启
- 不用于正式发布

---

## 21. 构建脚本

新增：

```powershell
.\scripts\build_desktop.ps1
```

流程：

```text
1. 清理临时目录
2. 校验 Python 3.11/3.12
3. 创建构建虚拟环境
4. 安装锁定依赖
5. npm ci
6. npm run typecheck
7. npm run test
8. npm run build
9. 后端 ruff
10. 后端 pytest
11. PyInstaller clean build
12. 验证 dist 目录
13. 启动 EXE smoke test
14. 检查健康接口
15. 检查静态首页
16. 关闭 EXE
17. 生成 portable ZIP
18. 生成 SHA256
19. 可选生成 Inno Setup 安装包
```

输出：

```text
release/
├─ ModWatcherAgent-portable-0.2.2-win-x64.zip
├─ ModWatcherAgent-portable-0.2.2-win-x64.zip.sha256
├─ ModWatcherAgent-Setup-0.2.2-win-x64.exe
└─ ModWatcherAgent-Setup-0.2.2-win-x64.exe.sha256
```

---

## 22. Inno Setup 安装包

## 22.1 安装位置

推荐：

```text
%LOCALAPPDATA%\Programs\ModWatcherAgent
```

优点：

- 不需要管理员权限。
- 符合单用户桌面应用场景。
- 避免 Program Files 写权限问题。
- 升级流程简单。

## 22.2 快捷方式

创建：

- 开始菜单快捷方式。
- 可选桌面快捷方式。
- 卸载入口。

## 22.3 用户数据

安装和升级绝不覆盖：

```text
%LOCALAPPDATA%\ModWatcherAgent
```

卸载时：

- 默认保留用户数据。
- 可提供复选框“同时删除数据库、设置和日志”。
- 默认不勾选。

## 22.4 WebView2 安装

安装器流程：

1. 检查 WebView2 Runtime。
2. 已安装：继续。
3. 未安装：运行 Evergreen Bootstrapper。
4. 安装失败：提示并中止客户端安装或允许稍后重试。

## 22.5 开机启动

首版不默认启用。

设置页中已有 `auto_start` 配置时，后续可通过：

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
```

或启动目录实现，但需要单独设计和测试。

---

## 23. GitHub Actions CI/CD

新增工作流：

```text
.github/workflows/desktop-release.yml
```

## 23.1 触发条件

```yaml
on:
  workflow_dispatch:
  push:
    tags:
      - "v*"
```

普通 PR 不必每次生成安装包，可运行轻量测试。

## 23.2 Windows 构建 Job

运行环境：

```yaml
runs-on: windows-latest
```

步骤：

1. Checkout。
2. Setup Python。
3. Setup Node。
4. 缓存 pip/npm。
5. 安装后端依赖。
6. 安装 PyInstaller/pywebview。
7. 前端 typecheck/test/build。
8. 后端 ruff/pytest。
9. 构建 EXE。
10. 执行 smoke test。
11. 生成 ZIP/SHA256。
12. 可选 Inno Setup。
13. 上传 workflow artifact。
14. Tag 构建时附加到 GitHub Release。

## 23.3 供应链约束

- GitHub Actions 使用固定 major 或 commit SHA。
- Python 依赖建议生成 lock 文件。
- npm 使用 `npm ci`。
- 发布产物生成 SHA256。
- Release 不包含 `.env`、数据库、日志和真实 API Key。
- CI 禁止把测试密钥写入日志。
- 后续加入代码签名时，证书和密码只放 GitHub Secrets。

---

## 24. 测试策略

## 24.1 单元测试

### RuntimePaths

覆盖：

- 源码模式。
- PyInstaller 模拟模式。
- `LOCALAPPDATA` 缺失。
- 自定义 `MW_USER_DATA_DIR`。
- 中文和空格路径。
- 路径创建失败。

### DesktopController

使用 fake window、fake tray 和 fake server：

- 最小化隐藏。
- 关闭取消并隐藏。
- 退出允许关闭。
- 重复退出幂等。
- 托盘失败降级。
- 后端启动失败。
- 后端超时。

### 数据迁移

覆盖：

- 新数据库不存在。
- 旧数据库存在。
- 新数据库已存在。
- WAL 数据。
- 损坏数据库。
- 无权限。
- 迁移中断。
- 完整性校验失败。

## 24.2 集成测试

- 启动嵌入式 FastAPI。
- `/api/health` 返回成功。
- `/` 返回 React HTML。
- `/assets/*` 返回静态文件。
- SQLite 在用户目录创建。
- Alembic 迁移可执行。
- Scheduler 启动/停止。
- API 设置可以保存。
- 日志写入用户日志目录。

## 24.3 打包测试

在干净 Windows Runner 上验证：

- 不依赖系统 Python。
- 不依赖 Node.js。
- EXE 可启动。
- WebView 窗口可创建。
- 托盘可创建。
- 关闭到托盘。
- 恢复窗口。
- 真正退出后端端口释放。
- 第二实例被阻止。
- 静态资源无 404。
- Alembic 资源未漏包。
- pystray backend 未漏包。
- WebView2 renderer 未漏包。

## 24.4 手工验收

测试矩阵：

```text
Windows 10 22H2 x64
Windows 11 当前稳定版 x64
100% / 125% / 150% DPI
单显示器 / 双显示器
中文用户名
安装路径含空格
无管理员权限用户
系统 Edge 存在
WebView2 缺失模拟
旧数据库迁移
无网络启动
```

---

## 25. 日志与可观测性

## 25.1 日志位置

```text
%LOCALAPPDATA%\ModWatcherAgent\logs\
├─ mod_watcher.log
├─ desktop.log
├─ startup.log
└─ crash.log
```

## 25.2 日志职责

`desktop.log`：

- 单实例。
- 目录初始化。
- WebView 创建。
- 托盘状态。
- 窗口事件。
- 后端线程状态。
- 退出流程。

`mod_watcher.log`：

- API。
- 调度任务。
- 数据源。
- AI。
- 通知。
- 数据库。

## 25.3 敏感信息

保留当前日志脱敏机制，并扩展：

- Authorization。
- API Key。
- Token。
- Webhook。
- Proxy password。
- Cookie。
- WebView/Playwright profile 内容不得写日志。

## 25.4 崩溃处理

主入口注册：

```python
sys.excepthook
threading.excepthook
```

未捕获异常写入 `crash.log`，包含：

- 应用版本。
- Windows 版本。
- frozen 状态。
- 用户数据目录。
- traceback。
- 当前生命周期状态。

不得包含 API Key 和 Cookie。

---

## 26. 安全设计

## 26.1 网络边界

桌面版后端只监听：

```text
127.0.0.1
```

默认不允许 LAN。

## 26.2 WebView 导航

- 应用主页面仅允许本地地址。
- 外部链接交给系统浏览器。
- 不在 WebView 内加载不受信任的完整第三方页面。
- LoversLab 登录继续使用独立系统浏览器/Playwright context。

## 26.3 API

保留现有 AccessPolicy。

建议桌面模式增加随机会话令牌：

```text
MW_DESKTOP_SESSION_TOKEN
```

WebView 首次加载时通过 HttpOnly Cookie 建立本地会话，用于降低本机其他网页调用本地 API 的风险。

这项可以在首版之后实施，不阻塞 EXE 打包。

## 26.4 设置中的密钥

当前 API Key 和 Token 仍保存在 SQLite 设置表中。

首版保持兼容，不在 EXE 改造中同时引入密钥加密迁移。

后续安全版本建议：

- Windows DPAPI。
- Windows Credential Manager。
- SQLite 只保存凭据引用。
- 提供旧明文密钥迁移。

---

## 27. 性能要求

目标指标：

```text
冷启动到窗口可交互：≤ 8 秒
热启动：≤ 4 秒
空闲内存：≤ 250 MB
空闲 CPU：接近 0%
窗口恢复：≤ 500 ms
正常退出：≤ 10 秒
```

这些是验收目标，不是当前实测值。

优化原则：

- 使用 onedir。
- 不在启动阶段执行网络发现。
- SQLite FTS 修复继续延迟执行。
- 不启动 Vite/Node。
- 不默认启动 Playwright 浏览器。
- WebView 只创建一个主窗口。
- 静态资源启用合理缓存。

---

## 28. 向后兼容

## 28.1 保留源码模式

继续支持：

```powershell
.\start-debug.bat
```

开发模式：

- Python venv。
- Vite dev server。
- 浏览器或现有托盘模式。
- 热更新。

## 28.2 保留服务器模式

Docker 和纯 FastAPI 部署不依赖 pywebview。

桌面模块不得被 `app.main` 强制导入，避免服务器安装也必须具备 Windows GUI 依赖。

建议将桌面依赖放入 optional dependency：

```toml
[project.optional-dependencies]
desktop = [
  "pywebview>=...",
  "pystray>=...",
  "Pillow>=...",
]
```

基础后端依赖中是否继续保留 pystray，可在重构后决定。

## 28.3 版本一致性

版本应只维护一个权威源，例如：

```text
backend/pyproject.toml
```

构建脚本同步生成：

- FastAPI version。
- 前端 version。
- Windows FileVersion。
- 安装器 version。
- Release 文件名。

避免多个文件手工维护 `0.2.2`。

---

## 29. 实施阶段

## 阶段 1：路径与可测试基础设施

- 新增 RuntimePaths。
- 改造 config、db、logger、browser profile、snapshot 路径。
- 添加路径单元测试。
- 保持现有源码模式通过。

验收：

- 源码模式行为不变。
- 测试可通过临时目录隔离数据库和日志。

## 阶段 2：嵌入式后端

- 新增 EmbeddedBackendServer。
- 新增健康接口。
- 后端进程内启动和停止。
- 添加启动失败回传。

验收：

- Python 直接运行 desktop entry 可启动后端。
- 不创建第二个 Python/Uvicorn 子进程。

## 阶段 3：pywebview 窗口

- 新增 DesktopController。
- 创建原生窗口。
- 处理关闭和最小化。
- 加入 WebView 数据目录。
- 处理 WebView2 缺失。

验收：

- 独立窗口显示完整 React UI。
- 关闭和最小化不停止任务。

## 阶段 4：托盘重构

- 抽取 TrayController。
- 复用现有菜单功能。
- 添加恢复窗口。
- 添加真正退出。
- 托盘失败降级。

验收：

- 托盘双击恢复。
- 退出后端口和进程全部释放。

## 阶段 5：PyInstaller

- 新增 spec。
- 修复资源路径。
- 处理 hidden imports。
- 构建 onedir。
- 打包静态前端、Alembic 和图标。

验收：

- 干净机器无 Python/Node 可运行。

## 阶段 6：迁移、安装器和 CI

- 旧数据库迁移。
- Portable ZIP。
- Inno Setup。
- GitHub Actions。
- SHA256。
- 发布文档。

验收：

- 升级不丢数据。
- Tag 可自动产生 Release 产物。

---

## 30. 预计修改文件

### 新增

```text
backend/desktop_app.py
backend/app/runtime_paths.py
backend/app/desktop/**
packaging/mod_watcher_agent.spec
packaging/version_info.txt
packaging/installer/ModWatcherAgent.iss
scripts/build_desktop.ps1
scripts/smoke_test_desktop.ps1
.github/workflows/desktop-release.yml
docs/desktop-client-technical-design.md
```

### 修改

```text
backend/pyproject.toml
backend/tray_app.py
backend/app/main.py
backend/app/config.py
backend/app/db.py
backend/app/logger.py
backend/app/services/browser/page_fetcher.py
backend/app/api/routes_loverslab_browser.py
frontend/package.json
README.md
DEPENDENCIES.md
build-release.bat
scripts/build_release.ps1
```

### 可能新增测试

```text
backend/tests/test_runtime_paths.py
backend/tests/test_desktop_controller.py
backend/tests/test_embedded_backend.py
backend/tests/test_database_migration.py
backend/tests/test_desktop_shutdown.py
```

---

## 31. 风险矩阵

| 风险 | 影响 | 概率 | 处理 |
|---|---:|---:|---|
| PyInstaller 漏掉动态导入 | 高 | 中 | spec hidden imports + 干净机 smoke test |
| Alembic 版本脚本未打包 | 高 | 中 | 显式 datas + 迁移测试 |
| WebView2 缺失 | 高 | 低/中 | 安装器检测 + Bootstrapper |
| 最小化后无法恢复 | 高 | 低 | 托盘失败降级，不隐藏窗口 |
| 退出时 Scheduler/浏览器未关闭 | 中 | 中 | 统一幂等 shutdown |
| SQLite 迁移丢失 WAL 数据 | 高 | 低 | SQLite Backup API |
| Playwright CLI 在冻结后失效 | 中 | 高 | 首版使用系统 Edge/Chrome |
| 杀毒软件误报 | 中 | 中 | onedir、代码签名、稳定版本信息 |
| 路径含中文/空格失败 | 中 | 中 | 全部使用 pathlib + 专项测试 |
| API Key 明文存储 | 高 | 已存在 | 记录风险，后续 DPAPI 迁移 |
| 发布包过大 | 中 | 中 | 排除不用的 GUI backend 和 Chromium |
| 端口被占用 | 中 | 低 | 启动前检测并给出明确错误 |

---

## 32. 验收标准

只有全部满足后，才能称为“Windows 独立客户端完成”。

### 安装和启动

- [ ] Windows 10/11 x64 可安装。
- [ ] 无 Python 环境可运行。
- [ ] 无 Node.js 环境可运行。
- [ ] 双击快捷方式打开独立窗口。
- [ ] 不弹出控制台窗口。
- [ ] 前端资源完整，无 404。
- [ ] 后端健康检查成功。

### 窗口和托盘

- [ ] 最小化后窗口隐藏到托盘。
- [ ] 关闭按钮隐藏到托盘。
- [ ] 托盘双击恢复窗口。
- [ ] 托盘“打开主界面”恢复窗口。
- [ ] 托盘“退出”真正结束。
- [ ] 托盘故障时不会产生无法恢复的隐藏应用。

### 数据

- [ ] 数据库位于 `%LOCALAPPDATA%`。
- [ ] 日志位于 `%LOCALAPPDATA%`。
- [ ] 浏览器 profile 位于 `%LOCALAPPDATA%`。
- [ ] 旧数据库可迁移。
- [ ] 升级不覆盖用户数据。
- [ ] 卸载默认保留用户数据。

### 功能回归

- [ ] Mod 列表可加载。
- [ ] 发现规则可执行。
- [ ] 收藏更新可执行。
- [ ] AI 设置可保存并调用。
- [ ] Telegram/Discord 配置保持兼容。
- [ ] APScheduler 在窗口隐藏时继续运行。
- [ ] 系统通知可用。
- [ ] LoversLab 可使用系统 Edge/Chrome 登录和抓取。

### 发布

- [ ] GitHub Actions 构建成功。
- [ ] Portable ZIP 生成。
- [ ] 安装包生成。
- [ ] SHA256 生成。
- [ ] 构建产物不包含数据库、日志和密钥。
- [ ] Release 文档说明 WebView2 和数据目录。

---

## 33. 发布建议

首个桌面版建议版本：

```text
0.3.0
```

发布产物：

```text
ModWatcherAgent-Setup-0.3.0-win-x64.exe
ModWatcherAgent-Portable-0.3.0-win-x64.zip
SHA256SUMS.txt
```

版本定位：

```text
0.3.0：Windows 独立桌面客户端首版
```

后续路线：

```text
0.3.1：稳定性、DPI、安装和迁移修复
0.4.0：自动更新与代码签名
0.5.0：凭据加密、第二实例唤醒、浏览器运行时管理
```

---

## 34. 最终决策摘要

本项目不需要重写为 Electron 或原生 WinUI。

最小、稳定且与现有架构一致的方案是：

```text
保留 React SPA
保留 FastAPI 和业务逻辑
保留 SQLite 和 Scheduler
将 Uvicorn 改成进程内线程
使用 pywebview 提供原生窗口
使用 pystray 提供系统托盘
使用 RuntimePaths 分离只读资源与用户数据
使用 PyInstaller onedir 生成独立客户端
使用 Inno Setup 生成无管理员安装包
使用 GitHub Actions 自动构建发布
```

实施时优先处理路径、生命周期和退出一致性，再处理打包。不要先写 PyInstaller spec 再被动修补路径问题，否则容易得到“能启动但升级丢数据、静态资源缺失、托盘无法退出”的脆弱客户端。
