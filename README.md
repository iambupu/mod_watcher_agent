<p align="center">
  <img src="docs/mwlogo.png" alt="Mod Watcher Agent" width="160" />
</p>

<h1 align="center">Mod Watcher Agent</h1>

<p align="center">面向个人、离线优先的 Mod 信息聚合、筛选和更新跟踪客户端，并提供 AI 摘要与多语言辅助。</p>

<p align="center">
  <img src="docs/Mod%20Watcher%20Agent.png" alt="Mod Watcher Agent 客户端界面" width="95%" />
</p>

## 客户端功能

- 发现：聚合 Nexus Mods 和 LoversLab 的公开 Mod 信息。
- 收藏：收藏 Mod 并持续跟踪版本变化。
- 更新：以时间线查看版本和变更记录。
- 规则：创建、测试和启停定期发现规则。
- AI：使用 OpenAI 或兼容 OpenAI 协议的供应商生成摘要和多语言内容。
- 通知：支持 Telegram、Discord 和 Windows 本地通知。
- 智能助手：基于本地数据检索和回答 Mod 相关问题。

本项目只保存公开元数据，不下载、不镜像 Mod 文件，也不绕过站点权限。

## 快速开始

### 运行要求

- Windows x64 系统。
- Microsoft Edge WebView2 Runtime。多数 Windows 系统已经预装。
- 可用的网络连接。需要访问 Nexus Mods、LoversLab 或所配置的 AI 服务时使用。

### 下载与运行

发布资产包括：

| 文件 | 用途 |
|---|---|
| `ModWatcherAgent-<version>-win-x64-portable.zip` | Windows 便携版独立客户端 |
| 同名 `.sha256` | 校验 ZIP 文件完整性 |

1. 下载 ZIP。
2. 把 ZIP 完整解压到普通目录，不要直接在压缩包内运行。
3. 保留 `ModWatcherAgent.exe` 与 `_internal` 目录的相对位置。
4. 双击 `ModWatcherAgent.exe`。
5. 首次启动后进入「设置」，填写需要使用的 Mod 来源、AI 和通知配置。

首次启动需要初始化 WebView2、数据库和缓存，可能比后续启动更慢。

### 校验下载文件

在下载目录打开 PowerShell：

```powershell
Get-FileHash .\ModWatcherAgent-<version>-win-x64-portable.zip -Algorithm SHA256
Get-Content .\ModWatcherAgent-<version>-win-x64-portable.zip.sha256
```

两处 SHA256 摘要应当一致。

## 窗口与系统托盘

- 点击窗口的最小化按钮会把窗口隐藏到系统托盘。
- 点击窗口的关闭按钮时，只要托盘运行正常，客户端也会隐藏到托盘并继续执行后台任务。
- 双击托盘图标或选择「打开主界面」可恢复窗口。
- 需要完全关闭客户端时，请在托盘菜单中选择「退出」。程序会关闭窗口、后台服务和托盘进程，并释放本地端口。
- 客户端采用单实例运行。重复启动时不会创建第二套后台服务。
- 如果托盘初始化失败，关闭窗口会直接退出，避免窗口被隐藏后无法恢复。

客户端后端只监听 `127.0.0.1:17500`，默认不会开放到局域网。

## 配置与数据目录

便携版只便携程序文件。配置、数据库、日志和 WebView 数据默认保存在：

```text
%LOCALAPPDATA%\ModWatcherAgent
```

常用路径：

| 内容 | 默认路径 |
|---|---|
| 配置目录 | `%LOCALAPPDATA%\ModWatcherAgent\config` |
| 高级环境配置 | `%LOCALAPPDATA%\ModWatcherAgent\config\.env` |
| 数据库选择记录 | `%LOCALAPPDATA%\ModWatcherAgent\config\database-selection.json` |
| 默认 SQLite 数据库 | `%LOCALAPPDATA%\ModWatcherAgent\data\mod_watcher.db` |
| 业务与桌面日志 | `%LOCALAPPDATA%\ModWatcherAgent\logs` |
| WebView 用户数据 | `%LOCALAPPDATA%\ModWatcherAgent\webview` |
| 数据迁移备份记录 | `%LOCALAPPDATA%\ModWatcherAgent\backups` |

在「设置 → 配置与数据库」中可以：

- 查看当前配置目录并点击「打开目录」。
- 查看默认数据库路径。
- 设置自定义数据库绝对路径或 `sqlite:///` 路径。
- 清空数据库路径，恢复使用默认数据库。

数据库路径保存后不会立即切换，必须从托盘完全退出并重新启动客户端。相对数据库路径会按配置目录解析，建议使用绝对路径避免歧义。

也可以通过 `MW_USER_DATA_DIR` 环境变量覆盖整个用户数据根目录。普通用户通常不需要设置它。

## 备份与删除

备份数据库前，先从托盘菜单退出客户端，然后复制实际使用的数据库文件。这样可以避免复制到仍在写入的 SQLite 数据库。

删除解压后的客户端目录只会删除程序，不会删除 `%LOCALAPPDATA%\ModWatcherAgent` 中的用户数据。

如果确定不再需要全部本地数据，请先退出客户端，再手动删除：

```text
%LOCALAPPDATA%\ModWatcherAgent
```

此操作会删除数据库、配置、日志和浏览器资料，无法撤销。

## 常见问题

### 首次启动很慢

首次启动会初始化 WebView2、SQLite 和运行缓存。如果刚清理过 WebView 缓存，下一次启动也可能稍慢。后续启动通常会更快。

### 点击关闭按钮后进程仍在

这是托盘运行模式的正常行为。关闭按钮默认隐藏窗口，后台任务继续运行。需要完全退出时，请右键托盘图标并选择「退出」。

### 托盘退出后进程仍未关闭

正常情况下，托盘退出会直接关闭窗口和后台服务。如果仍有 `ModWatcherAgent.exe` 进程，请查看：

```text
%LOCALAPPDATA%\ModWatcherAgent\logs\desktop.log
%LOCALAPPDATA%\ModWatcherAgent\logs\crash.log
```

随后可在任务管理器结束残留进程，并携带日志反馈问题。

### 双击后没有显示窗口

1. 检查系统托盘中是否已有客户端图标。
2. 确认没有旧的 `ModWatcherAgent.exe` 实例残留。
3. 安装或修复 Microsoft Edge WebView2 Runtime。
4. 检查 `desktop.log` 和 `crash.log`。
5. 确认本机端口 `17500` 没有被其他程序占用。

### 修改数据库路径后没有生效

1. 在设置中保存数据库路径。
2. 从托盘菜单选择「退出」，确认进程已经结束。
3. 重新启动客户端。
4. 回到「设置 → 配置与数据库」核对路径。

数据库路径留空时，客户端使用 `%LOCALAPPDATA%\ModWatcherAgent\data\mod_watcher.db`。

### LoversLab 登录窗口无法打开

确认 Microsoft Edge 或 Google Chrome 可以正常启动。浏览器资料默认保存在 `%LOCALAPPDATA%\ModWatcherAgent\data\browser_profiles`。

### 安全软件提示未知应用

当前便携版没有声明 Windows 代码签名。请确认下载来源，并使用同名 `.sha256` 文件核对完整性。

## 开发者构建

普通用户不需要执行本节命令。

开发环境要求：

- Python 3.11+
- Node.js 18+
- PowerShell 5.1+

在仓库根目录运行：

```powershell
.\build-desktop.bat
```

完整构建会执行前端类型检查、测试和构建，随后运行 PyInstaller onedir 打包、独立客户端 smoke test，并生成：

```text
dist-desktop\ModWatcherAgent\ModWatcherAgent.exe
release\ModWatcherAgent-<version>-win-x64-portable.zip
release\ModWatcherAgent-<version>-win-x64-portable.zip.sha256
```

可用构建参数：

```powershell
.\build-desktop.bat -SkipTests
.\build-desktop.bat -SkipFrontendBuild
.\build-desktop.bat -SkipSmokeTest
.\build-desktop.bat -SkipPortable
```

`-SkipFrontendBuild` 只适用于 `frontend\dist` 已经存在的情况。

更多实现与依赖信息：

- [依赖说明](./DEPENDENCIES.md)
- [代码风格](./CODE_STYLE.md)

## 许可证

本项目使用 [Apache License 2.0](./LICENSE)。
