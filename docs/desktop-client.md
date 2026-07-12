# Windows 桌面客户端指南

本文面向使用 Mod Watcher Agent Windows 独立客户端的普通用户，也为需要诊断、迁移或源码兼容模式的高级用户提供准确边界。

> 当前状态：桌面代码基线 `ec5dedb` 已在本机使用 Python 3.12.13 x64 与 Inno Setup 6.7.3 完整执行 `scripts/build_desktop.ps1`，退出码为 0；backend、Ruff、前端安装/类型检查/测试/构建、PyInstaller onedir、packaged smoke、portable、Setup 和 SHA256 全链均执行完成。构建脚本已将含陈旧安装器的输入目录自动收敛为精确 4 件相互匹配的当前资产；最终 onedir 与静默安装后的 EXE 都通过强化无 GUI smoke，两轮静默逐用户安装/卸载、默认保留用户数据和开机启动项归属清理也已实测。以上只证明本机 headless 构建与静默安装路径，不代表 GitHub-hosted workflow、tag Release、Windows 10/11 GUI、DPI/双屏/托盘、缺失 WebView2、升级、交互删除或代码签名已经验收。逐项边界见 [验收记录](./desktop-client-acceptance.md)。

## 1. 客户端形态

Windows 桌面版采用以下结构：

```text
ModWatcherAgent.exe
  ├─ 主线程：pywebview / WebView2 原生窗口
  ├─ 后台非 daemon 线程：进程内 FastAPI / Uvicorn
  ├─ 托盘线程：pystray
  └─ FastAPI 生命周期：SQLite、APScheduler、浏览器资源
```

React 界面由同一进程中的 FastAPI 托管。客户端不会为 Uvicorn 再启动一个 Python 子进程，也不会启动 Vite 或 Node.js。

正常桌面模式默认监听：

```text
http://127.0.0.1:17500
```

该地址只绑定回环接口。客户端会先加载用户 `.env`，只解析一次地址；取得单实例锁后、数据库迁移前即独占并监听该端口，再把同一 socket 移交给 Uvicorn。端口被占用时会在迁移前失败并写入日志，不会自动改用随机端口。随机端口只用于隔离 smoke test。

## 2. 选择安装版或便携版

| 版本 | 文件名 | 特点 |
|---|---|---|
| 安装版 | `ModWatcherAgent-Setup-<version>-win-x64.exe` | 推荐；逐用户安装、开始菜单、可选桌面快捷方式、标准卸载入口。 |
| 便携版 | `ModWatcherAgent-<version>-win-x64-portable.zip` | 无需安装；必须完整解压 onedir。 |

两者运行后都把可写数据放到 `%LOCALAPPDATA%\ModWatcherAgent`。便携版不会把数据库和登录 profile 写进 EXE 旁边，因此“便携”只指应用文件无需安装。

发布页未出现某个资产时，表示当前 Release 没有交付该资产。不要根据文档中的预期文件名推断它已经生成。

## 3. 下载后先校验 SHA256

每个 ZIP 或 EXE 应有同名 `.sha256`：

```powershell
$artifact = ".\ModWatcherAgent-<version>-win-x64-portable.zip"
$actual = (Get-FileHash -LiteralPath $artifact -Algorithm SHA256).Hash.ToLowerInvariant()
$expectedLine = (Get-Content -LiteralPath "$artifact.sha256" -Raw).Trim()
$actual
$expectedLine
```

`.sha256` 应使用以下格式：

```text
<64 位小写十六进制摘要><两个空格><对应资产文件名>
```

摘要或文件名不一致时不要运行资产，应重新从可信 Release 页面下载。

## 4. 使用安装版

### 4.1 安装

1. 退出正在运行的 Mod Watcher Agent。
2. 运行安装器。
3. 按需勾选桌面快捷方式；开始菜单快捷方式默认创建。
4. 完成后从开始菜单打开应用。

默认安装目录：

```text
%LOCALAPPDATA%\Programs\ModWatcherAgent
```

安装器使用 `PrivilegesRequired=lowest`，面向当前用户，不要求管理员权限。升级前应先完整退出客户端；安装器已配置 `AppMutex` 与 `CloseApplications` 来检测并尝试关闭同一应用，但真实升级行为仍待 M14 人工验收。程序文件不会写入用户数据目录。

当前本机验收已把最终 Setup 两次静默安装到含中文和空格的临时目录，安装后 EXE smoke 与静默卸载均返回 0，用户数据 sentinel 得到保留。卸载会删除精确归属当前安装 EXE 的 HKCU Run 值，但保留用户改写为其他命令的同名值；测试后安装文件、Run 值、HKCU 卸载项、进程、数据目录和本轮临时目录均无残留。该证据不包含安装向导、开始菜单/桌面快捷方式、覆盖升级、交互卸载或普通非管理员干净账户测试。

### 4.2 WebView2 安装策略

安装器会检查 HKCU/HKLM 的 WebView2 Runtime 版本。

- 构建者显式提供且通过 Microsoft 签名与产品身份校验的 Evergreen Bootstrapper 时，安装器可以在缺失 Runtime 时运行 `/silent /install`，检查退出码并再次检查注册表。
- 未提供 Bootstrapper 时，安装器不会联网下载文件，只会提示 [Microsoft WebView2 官方下载页面](https://developer.microsoft.com/microsoft-edge/webview2/)。
- 当前 GitHub Actions workflow 没有传入 `-WebView2BootstrapperPath`，因此按当前配置构建的安装器不会内置 Bootstrapper。
- WebView2 仍缺失时，安装完成后不会自动启动应用。直接运行 EXE 时，只有启动异常文本被识别为 WebView2/EdgeChromium 相关错误，客户端才会在原生错误框中附上官方地址；缺失 Runtime 的真实机器路径仍待 M07 验收。

## 5. 使用便携版

1. 创建一个普通目录，例如 `D:\Apps\ModWatcherAgent`。
2. 把 ZIP 完整解压到该目录。
3. 确认目录中同时存在 `ModWatcherAgent.exe` 与 `_internal`。
4. 双击 `ModWatcherAgent.exe`。

不要：

- 直接在压缩软件预览窗口中运行 EXE。
- 只复制 EXE 而丢弃 `_internal`。
- 把发布目录中的旧 ZIP 与当前源码或当前 `dist-desktop` 混为同一构建证据。

删除便携版程序目录不会删除 `%LOCALAPPDATA%\ModWatcherAgent`。如需彻底清理，请先完整退出，再备份并手动处理用户数据。

## 6. 窗口、托盘与完整退出

### 6.1 最小化与关闭

当托盘健康时：

- 点击最小化：隐藏窗口，后端和定时任务继续运行。
- 点击关闭：取消真正关闭并隐藏窗口。
- 托盘双击或「打开主界面」：显示并恢复窗口。

当托盘启动失败或运行中失效时：

- 客户端把托盘标记为不可用。
- 已隐藏窗口会尝试恢复。
- 后续最小化不会把窗口隐藏到不可恢复状态。
- 点击关闭会真正退出。

### 6.2 托盘菜单

当前菜单包括：

- 打开主界面
- 立即检查新 Mod
- 检查收藏更新
- 暂停/恢复定时任务
- 打开日志目录
- 退出

托盘 API 操作只访问本机回环地址，并忽略系统代理环境变量。

### 6.3 真正退出

请使用托盘「退出」。正常的统一退出路径会停止托盘、请求 FastAPI/Uvicorn 生命周期结束、销毁窗口并释放单实例锁。FastAPI 生命周期负责停止调度器并关闭持久浏览器资源。如果非 daemon 后端线程在超时后仍未停止，客户端会保留单实例锁、记录严重错误并刷新日志，然后以非零状态强制结束进程，避免留下一个无窗口的半退出实例。

任务管理器中不再存在 `ModWatcherAgent.exe`，且端口 `17500` 已释放，才表示完全退出。直接结束进程只应作为故障恢复手段。

## 7. 单实例与启动顺序

Windows 正式路径使用：

```text
Local\ModWatcherAgentDesktop
```

第二个实例会显示「程序已在运行，请从系统托盘打开」并返回，不会再次迁移数据库或启动另一套后端。

启动顺序为：

1. 解析并创建运行时目录。
2. 注入桌面环境变量和本地访问约束。
3. 配置桌面日志与异常钩子。
4. 获取单实例锁。
5. 检查旧 SQLite 迁移。
6. 启动进程内后端；只在自有 Uvicorn 实例确认绑定后才接受 `/api/health` 就绪响应。
7. 后端健康后创建窗口与托盘。

后端未就绪时不会先展示空白 WebView。

## 8. 用户数据目录

默认根目录：

```text
%LOCALAPPDATA%\ModWatcherAgent
```

| 路径 | 内容 | 备份建议 |
|---|---|---|
| `data\mod_watcher.db` | SQLite 主数据库 | 重要；完整退出后复制。 |
| `data\browser_profiles` | LoversLab 登录 profile | 包含 Cookie，按敏感数据保护。 |
| `data\snapshots` | 页面 HTML 快照 | 排障后可按需清理。 |
| `config\.env` | 高级环境默认值 | 可能包含密钥，禁止公开。 |
| `config\game_aliases.json` | 内置游戏别名的用户副本与后续学习结果 | 可备份；已有用户文件不会被启动流程覆盖。 |
| `logs\mod_watcher.log` | 后端业务日志 | 分享前仍应人工检查。 |
| `logs\desktop.log` | 桌面启动与整体生命周期日志 | 首选排障文件；当前不保证记录每一次托盘/窗口适配器内部错误。 |
| `logs\crash.log` | 未捕获异常与生命周期状态 | 首选排障文件。 |
| `webview` | WebView Cookie、LocalStorage 与会话状态 | 不作为业务配置唯一来源。 |
| `runtime` | 迁移锁等运行时协调文件 | 不要在运行中删除；Windows 单实例使用 Named Mutex，不依赖固定锁文件。 |
| `backups\migration.json` | 旧数据库迁移元数据 | 记录源、目标、时间、大小和 integrity。 |

桌面日志使用轮转文件并在写入前脱敏 Authorization、API Key、Token、Webhook、密码、Cookie 和 profile 内容。脱敏是防御措施，不是分享日志的免责保证；提交 Issue 前仍要人工检查。

冻结版首次启动且 `config\game_aliases.json` 不存在时，会把只读 bundle 中的 `backend\game_aliases.json` 原子播种到用户配置目录。若用户文件已经存在，或另一个启动实例在竞态中先创建了它，客户端会保留现有文件并清理自己的临时文件，不会用内置副本覆盖用户学习结果。

## 9. 旧 SQLite 迁移

只有新数据库不存在时才迁移。候选顺序为：

```text
<exe_dir>\backend\mod_watcher.db
<exe_dir>\mod_watcher.db
<current_working_directory>\backend\mod_watcher.db
```

迁移行为：

- 选择第一个存在的候选。
- 以只读 URI 打开源数据库。
- 使用 SQLite Backup API 捕获已提交的 WAL 数据。
- 在临时数据库上运行完整 `PRAGMA integrity_check`。
- 使用跨进程锁、原子 no-clobber 发布和精确临时文件清理。
- 写入 `backups\migration.json`。
- 永不删除源数据库。

新数据库已经存在时不会重复迁移。旧数据库位于其他任意目录时不会自动发现，可先备份，再把它放到受支持候选位置后启动；不要覆盖已有的新数据库。

## 10. 浏览器与 LoversLab

独立窗口使用 WebView2；LoversLab 登录与抓取使用 Playwright 驱动的持久浏览器 context。候选策略是优先尝试系统 Microsoft Edge 或 Google Chrome，最后才使用已经安装的 Playwright Chromium。已探测到的系统安装会先进入候选，代码还会补试缺少的系统 channel，因此不应把状态页显示的单个候选理解为已经实际启动成功。

不同浏览器使用独立 profile 后缀，避免多个 channel 锁住同一用户数据目录。

冻结版的 `/install-chromium` 操作会返回 `unsupported_in_packaged_app`，不会递归执行主 EXE。系统浏览器都缺失时，请安装 Edge 或 Chrome。

## 11. 配置与安全边界

- 桌面版强制 `127.0.0.1`、`MW_ALLOW_LAN=false` 和 `LOCAL_ONLY_API=true`。
- 现有 AccessPolicy 继续保护本地 API。
- 外部站点链接交给系统浏览器，不在主 WebView 中加载完整第三方页面。
- Release 扫描拒绝 `.env*`、数据库及派生/备份文件、日志、浏览器 profile、快照、缓存、测试目录和明显的凭据文件。
- API Key 与 Token 当前仍以兼容格式保存在本地 SQLite；DPAPI/Credential Manager 不在首版范围。
- 当前没有内置自动更新器，也没有 Windows 代码签名完成证据。

不要把 `.env`、数据库、浏览器 profile 或未经人工检查的日志上传到公开渠道。

### 11.1 开机启动

在设置页启用开机启动时，Windows 冻结版会在当前用户的以下位置写入名为 `ModWatcherAgent` 的字符串值：

```text
HKCU\Software\Microsoft\Windows\CurrentVersion\Run
```

值数据是带引号的当前 EXE 绝对路径，例如：

```text
"C:\Users\<user>\AppData\Local\Programs\ModWatcherAgent\ModWatcherAgent.exe"
```

该功能不创建 Windows 服务或计划任务，也不要求管理员权限；关闭开机启动会删除该 Run 值。卸载时，安装器只在该值仍精确指向当前安装目录中的 `ModWatcherAgent.exe` 时删除它；用户或其他工具改写过的同名值会被保留。安装版路径通常稳定。便携版若在启用后移动或删除解压目录，注册表仍指向旧路径；应先关闭开机启动，移动后从新位置运行客户端并重新启用。源码模式为兼容原入口，仍注册 PowerShell 调用仓库 `start.ps1 -Tray`，不是普通用户的独立 EXE 路径。

## 12. 卸载、备份与重置

### 12.1 安装版卸载

- 默认保留 `%LOCALAPPDATA%\ModWatcherAgent`。
- 静默卸载始终保留用户数据。
- 只有仍精确指向当前安装 EXE 的 `HKCU\...\Run\ModWatcherAgent` 值会被删除，用户改写值会被保留。
- 交互卸载只在卸载主体完成后询问是否删除数据，并要求连续两次确认。
- 最终删除不可恢复，包含数据库、设置、日志、浏览器资料和快照。

最终 Setup 的两轮本机静默新装/卸载、安装后 smoke、默认保留用户数据、归属开机启动项删除与用户改写项保留已执行通过。覆盖升级、安装向导、快捷方式、交互卸载双确认与实际删除用户数据仍未执行，不能由静默路径推断为通过。

### 12.2 安全备份

1. 使用托盘「退出」。
2. 确认进程与端口已结束。
3. 复制整个 `%LOCALAPPDATA%\ModWatcherAgent` 到备份位置。
4. 需要恢复时，在应用完全退出后恢复目录。

不要在 SQLite 正在写入时只复制 `mod_watcher.db`，否则可能遗漏 WAL 中已提交的数据。

### 12.3 重置排障

完整退出后，可把用户数据目录重命名为 `ModWatcherAgent.backup`，再启动客户端生成全新目录。确认问题与旧配置无关后，再决定恢复哪些数据。不要直接删除原目录。

## 13. 源码、Docker 与传统启动兼容

源码模式继续使用原布局：

| 内容 | 源码模式位置 |
|---|---|
| 数据库 | `backend\mod_watcher.db` |
| 日志 | `log` |
| 浏览器 profile | `backend\data\browser_profiles` |
| 前端静态资源 | `frontend\dist` |

开发者入口：

```powershell
.\start-debug.bat
```

传统源码用户入口仍可使用：

```powershell
.\start-user.bat
```

这些脚本会使用或创建 Python 环境，不是独立客户端的普通用户路径。Docker 和纯 FastAPI 部署不会强制导入 pywebview、pystray 或 Windows GUI 依赖。

## 14. 故障排查

### 14.1 窗口未出现或提示 WebView2

- 安装 [WebView2 Runtime](https://developer.microsoft.com/microsoft-edge/webview2/)。
- 查看 `logs\desktop.log` 和 `logs\crash.log`。
- 确认完整解压 `_internal`，不要只运行孤立 EXE。

### 14.2 端口 17500 被占用

```powershell
Get-NetTCPConnection -LocalPort 17500 -State Listen
```

确认占用进程后安全退出它，再重启客户端。客户端会在数据库迁移前拒绝占用状态，普通桌面模式不会自动选择新端口。

### 14.3 托盘图标缺失

- 检查 Windows 托盘折叠区。
- 查看 `desktop.log` 了解整体启动阶段；当前版本不保证把每个托盘适配器内部错误写入该文件。
- 托盘不可用时不要期待关闭到托盘；关闭窗口应走完整退出。

### 14.4 数据库迁移报错

- 保留旧数据库和所有 sidecar。
- 查看迁移错误；只有 `migration.json` 存在时才核对它，失败路径可能回滚或删除新元数据。
- 检查用户目录权限、可用空间和数据库完整性。
- 不要创建空文件覆盖目标数据库。

### 14.5 LoversLab 浏览器不可用

- 确认 Edge 或 Chrome 已安装并能正常打开。
- 不要在打包版中尝试安装 Playwright Chromium。
- profile 可能被另一个浏览器进程锁定；先完整退出相关浏览器和客户端。

### 14.6 安全软件拦截

- 核对 Release 来源和 SHA256。
- 当前 EXE 与 Setup 均为 `NotSigned`，SmartScreen/杀毒软件声誉仍需发布阶段处理。
- 不要通过关闭系统安全防护来绕过来源不明的资产。

## 15. 已验证与尚未验证

已在本机或自动测试中验证的范围包括：

- RuntimePaths、回环绑定和导入顺序。
- SQLite WAL 迁移、完整性、并发与 no-clobber 边界。
- 进程内 Uvicorn 的就绪、停止和端口释放。
- 窗口/托盘/单实例适配器的 fake 驱动生命周期测试。
- 桌面日志与崩溃日志脱敏。
- PyInstaller onedir 构建、x64 PE 与必需 DLL 检查。
- 完整本机构建链、陈旧受控制品自动清理、精确 4 件本地资产及对应 SHA256。
- 最终 onedir 和静默安装后 EXE 的真实无 GUI packaged smoke，包括 health、React HTML shell、全部引用的本地脚本/样式、隔离数据库/日志、进程与端口释放。
- 最终 Setup 的两轮本机静默逐用户安装/卸载、默认保留用户数据、归属开机启动项删除和用户改写项保留。
- portable、安装器和 workflow 的静态/动态契约测试，包括不覆盖已有 Release 二进制和显式 release notes。

尚未取得完成证据的范围包括：

- GitHub-hosted `workflow_dispatch` 和 tag Release。
- 干净 Windows 10/11 x64、无 Python/Node 环境。
- 100% / 125% / 150% DPI、单/双显示器。
- 中文用户名和普通非管理员账户的完整 GUI 流程；当前只验证了含中文和空格的静默安装目录。
- 缺失 WebView2 机器和 Bootstrapper 成功/失败路径。
- 覆盖升级、交互卸载双确认与删除用户数据。
- 重新登录开机启动、设置页关闭 Run 值和移动 portable 后重新启用。
- 真实 pywebview 窗口、系统托盘、LoversLab 登录、通知和完整功能回归。
- 冷/热启动、内存、CPU、窗口恢复和退出性能目标。

逐项状态和风险见 [桌面客户端验收记录](./desktop-client-acceptance.md)。
