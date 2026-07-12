# Windows 桌面客户端验收记录

本文把 [Windows 桌面客户端技术设计](./desktop-client-technical-design.md) 的目标、风险和验收标准映射到当前代码、自动测试、本机产物检查、GitHub 远端验收或 Windows 人工矩阵。

## 1. 结论摘要

截至 2026-07-12：

- 桌面运行时、迁移、生命周期、日志、PyInstaller、portable、Inno 脚本和发布 workflow 均已有实现与自动测试。
- 桌面代码基线 `5c10a62` 已在本机使用 Python 3.12.13 x64 与 Inno Setup 6.7.3 完整执行 `scripts/build_desktop.ps1`，退出码为 0。该命令实际经过 backend 测试、Ruff、`npm ci`、前端 typecheck/test/build、PyInstaller onedir、packaged smoke、portable、Inno 和 SHA256 阶段。
- 最终 onedir 含 1,045 个文件；EXE 为 x64 PE，7 项关键资源存在，onedir 与 ZIP 禁入扫描通过。ZIP 内 EXE 与 `dist-desktop` EXE 的 SHA256 一致。
- 当前本地 `release` 精确包含 portable、Setup 及两个同名 `.sha256`；4 件资产与桌面代码基线对应，摘要和文件名严格匹配。
- build 后独立 packaged smoke 以端口 4779 通过；health、React 根页面、隔离数据库/日志、进程、端口和临时目录清理均通过。
- 最终 Setup 已静默逐用户安装到含中文和空格的临时目录；安装后 EXE smoke 以端口 5037 通过，静默卸载返回 0，用户数据 sentinel 保留，安装文件、HKCU 卸载项、进程和本轮安装/smoke 临时目录均无残留。
- 当前 EXE 与 Setup 的 Authenticode 状态均为 `NotSigned`。
- smoke 端口握手修复的独立复审为 P0/P1/P2 全部 0；focused 测试为 142 passed，实现者最新完整 backend 为 1,254 passed。
- 没有 GitHub-hosted `workflow_dispatch` 或 tag Release 的执行证据。
- 没有完成 Windows 10/11、DPI、双屏、缺失 WebView2、真实 GUI/托盘、真实旧数据库迁移、升级、交互删除和代码签名矩阵。

因此，当前状态是「本机完整构建、4 件本地产物、headless smoke 与静默安装生命周期已有完成证据；远端发布和 GUI/人工矩阵仍未完成」，不能宣称技术设计第 32 节的全部验收标准已经通过。

## 2. 状态定义

| 状态 | 含义 |
|---|---|
| 自动通过 | 当前代码对应的单元、集成或契约测试已在本机执行通过。 |
| 本机产物通过 | 对真实 onedir/EXE/ZIP 执行过构建或 smoke 检查。只代表该本机和该产物。 |
| 静态通过 | 配置、脚本、YAML 或 Inno 语义已解析/检查，但没有执行对应外部系统。 |
| 部分通过 | 自动或静态证据存在，但仍缺真实 GUI、干净系统、远端或安装器路径。 |
| 未执行 | 当前没有可信执行证据。 |
| 非首版范围 | 技术设计明确列为后续能力，不阻塞首版。 |

## 3. 当前证据快照

本节区分两类证据：HEAD、资产大小/摘要、文件数、资源和签名状态可从当前工作区直接复核；构建退出码、端口 4779/5037 与静默安装生命周期来自本轮 Task 11 会话的执行输出，仓库中没有对应的持久 transcript，不应写成可由日志文件复验。

### 3.1 自动测试

当前桌面相关测试覆盖：

- `backend/tests/test_runtime_paths.py`
- `backend/tests/test_desktop_runtime_integration.py`
- `backend/tests/test_database_migration.py`
- `backend/tests/test_embedded_backend.py`
- `backend/tests/test_desktop_controller.py`
- `backend/tests/test_desktop_window.py`
- `backend/tests/test_desktop_tray.py`
- `backend/tests/test_desktop_app.py`
- `backend/tests/test_single_instance.py`
- `backend/tests/test_desktop_logging.py`
- `backend/tests/test_packaging_contract.py`
- `backend/tests/test_desktop_release_workflow.py`
- `backend/app/tests/test_windows_autostart_service.py`
- 浏览器与 LoversLab 相关测试。

Task1–8 报告记录了逐阶段 RED/GREEN、完整 backend 回归和 Ruff 结果。Task 11 的 smoke 端口握手 focused suite 为 `142 passed`，独立复审结论为 P0/P1/P2 全部 0；本轮最终 Python 3.12 backend 回归为 `1,254 passed`，Ruff 通过。完整 `scripts/build_desktop.ps1` 还实际执行 backend/Ruff 与 `npm ci`、前端 typecheck/test/build 并整体退出 0；随后独立复验前端 typecheck、35 个测试文件中的 168 个测试和 production build，均通过。

### 3.2 本机真实产物

已验证（针对桌面代码基线 `5c10a62` 的最终 `dist-desktop` 产物）：

- `dist-desktop\ModWatcherAgent\ModWatcherAgent.exe` 可运行 `--smoke-test`。
- build 后独立 smoke 使用端口 4779，启动真实进程内 FastAPI，检查 `/api/health` 与 `/`，创建隔离数据库和 `desktop.log`，随后确认进程、同一端口和临时目录清理。
- EXE 的 PE Machine 为 `0x8664`。
- onedir 共 1,045 个文件；前端 `index.html`、Alembic 配置、游戏别名、WebView2 Core/WinForms、x64 Loader 与 `Python.Runtime.dll` 共 7 项关键资源存在。
- onedir 与 portable ZIP 禁入扫描没有发现运行时数据库、日志、profile、快照、缓存、测试或明显凭据。
- EXE 的 Authenticode 状态为 `NotSigned`。

没有由该 smoke 验证：

- pywebview 窗口实际创建。
- WebView2 renderer 实际显示。
- 系统托盘实际创建和交互。
- pywebview/托盘驱动下的升级或交互卸载。
- DPI、多显示器、通知、LoversLab 登录和业务功能人工回归。

### 3.3 当前 Release 目录

当前本地 `release` 精确包含以下 4 件资产：

| 资产 | 大小 | SHA256 / 校验 |
|---|---:|---|
| `ModWatcherAgent-0.2.2-win-x64-portable.zip` | 81,104,020 bytes | `1b63f012261d8b9003015db081fa413a537e3d4cfc8c554fcc2c9178ca9e0cbe` |
| `ModWatcherAgent-0.2.2-win-x64-portable.zip.sha256` | 110 bytes | 摘要与文件名严格匹配 portable ZIP。 |
| `ModWatcherAgent-Setup-0.2.2-win-x64.exe` | 58,979,282 bytes | `1bd243fdf3200be42ef1d6f8c892fcab85ab3d1cfc2f41f7cc42abf79ce4cc09` |
| `ModWatcherAgent-Setup-0.2.2-win-x64.exe.sha256` | 107 bytes | 摘要与文件名严格匹配 Setup。 |

portable ZIP 含 1,045 个文件，ZIP 内 EXE 与当前 onedir EXE 的 SHA256 相同。完整构建使用已校验的 Inno Setup 6.7.3 并退出 0；最终 Setup 与 EXE 的 Authenticode 状态均为 `NotSigned`。这些是本地产物，不是 GitHub Release 资产。

最终 Setup 的本机静默生命周期证据为：安装到含中文和空格的临时目录返回 0；安装后 EXE smoke 在端口 5037 通过；静默卸载返回 0；LocalAppData 用户数据 sentinel 保留；安装文件、HKCU 卸载项、进程和本轮安装/smoke 临时目录无残留。该证据不包含覆盖升级、安装向导、快捷方式、交互卸载双确认或删除用户数据。

### 3.4 GitHub Actions

`.github/workflows/desktop-release.yml` 已具备：

- `workflow_dispatch` 与 `v*` tag 触发。
- Windows 2025 Runner、Python 3.12、Node.js 24。
- backend tests/Ruff、frontend typecheck/tests/build。
- 固定 SHA 的 GitHub Actions。
- Inno Setup 6.7.3 官方不可变 Release、GitHub attestation 和 Authenticode 验证。
- 真实 desktop build、packaged smoke、精确 4 件资产与 SHA256 复验。
- tag 版本一致性和幂等 `gh release`。

这些是代码与本地契约证据。尚未执行 GitHub-hosted job，不能写成远端构建或发布成功。

## 4. 分阶段实施映射

| 阶段 | 当前交付 | 证据 | 状态 | 剩余工作 |
|---|---|---|---|---|
| Task 1：RuntimePaths | 源码/冻结路径、目录创建、本地绑定环境 | `test_runtime_paths.py` | 自动通过 | 中文用户名真实 Windows 流程见 M05。 |
| Task 2：后端资源与 health | 前端/Alembic/浏览器路径、`/api/health`、生命周期清理 | `test_desktop_runtime_integration.py` | 自动通过 | 干净发布机静态资源回归见 M01/M02。 |
| Task 3：SQLite 迁移 | Backup API、WAL、integrity、锁、no-clobber、元数据 | `test_database_migration.py` | 自动通过 | 真实旧用户数据库见 M10。 |
| Task 4：进程内 Uvicorn | 非 daemon 线程、HTTP readiness、幂等 stop、端口释放 | `test_embedded_backend.py` | 自动通过 | 真实桌面长时运行见 M08/M09。 |
| Task 5：窗口/托盘/单实例 | controller、pywebview、pystray、Named Mutex、降级退出 | controller/window/tray/single-instance tests | 自动通过 | fake 驱动不能代替真实 GUI，见 M03/M04/M08。 |
| Task 6：依赖/浏览器/日志/smoke | desktop extras、冻结 Chromium 禁用、脱敏日志、smoke CLI | desktop app/logging/browser tests | 自动通过 | 真实浏览器与通知见 M12。 |
| Task 7：onedir/portable | spec、构建脚本、x64/关键资源/禁入、portable/SHA256 | 完整构建；1,045 文件；当前 ZIP/SHA；独立 smoke | 本机产物通过 | GitHub-hosted 复现见 R01/R04。 |
| Task 8：Inno/WebView2 | 逐用户安装器、条件 Bootstrapper、默认保留数据 | 最终 Setup 构建；静默新装/smoke/卸载与 sentinel 保留 | 部分通过 | 缺失 WebView2、升级和交互路径见 M07/M14。 |
| Task 9：发布 workflow | 供应链校验、质量门、4 件资产、tag Release | workflow tests、YAML/PowerShell 解析 | 静态通过 | GitHub-hosted 运行见 R01、R02、R04。 |
| Task 10：用户文档 | README、依赖、用户指南、验收与风险 | strict UTF-8、placeholder 0、本地断链 0、改动文档尾空格 0、diff-check 通过 | 自动通过 | 随后续远端/人工证据继续更新。 |
| Task 11：最终发布检查 | 全量测试、前端、完整构建、产物检查、人工矩阵 | 完整 build 退出 0；本地产物/smoke/静默安装生命周期通过 | 部分通过 | 完成 R01/R02/R04 与剩余 Windows GUI/人工矩阵。 |

## 5. 逐项需求映射

### 5.1 平台、分发与架构

| ID | 技术设计要求 | 当前证据 | 状态 | 剩余验收 |
|---|---|---|---|---|
| A01 | Windows 10/11 x64 | 构建脚本限制 Windows 64 位；PE `0x8664` 测试 | 部分通过 | M01、M02 |
| A02 | 用户无需 Python/Node | PyInstaller onedir 包含运行时；本机 EXE smoke | 部分通过 | 干净机 M01、M02 |
| A03 | 独立 EXE + React 静态前端 | spec 打包 `frontend/dist`；smoke 检查 `/` | 本机产物通过 | M01、M02、M08 |
| A04 | FastAPI 进程内运行，不建 Uvicorn 子进程 | `EmbeddedBackendServer` 与入口测试 | 自动通过 | M09 长时退出 |
| A05 | onedir 为首发形态 | spec 使用 `COLLECT`；最终 onedir/ZIP 各 1,045 个文件 | 本机产物通过 | GitHub Release R04 |
| A06 | 安装版与 portable | 本地 portable 与 Setup 已生成；静默安装/卸载通过 | 部分通过 | 远端 R04 与交互安装 M14 |
| A07 | 保留源码/Docker/服务器模式 | `app.main` 不强制导入 GUI；源码路径测试 | 自动通过 | 源码/Docker发布前回归 M12 |
| A08 | 不改变 React/API/状态数据契约 | 桌面层复用现有 FastAPI/React；backend/frontend 测试门 | 部分通过 | 真实业务功能 M12 |

### 5.2 窗口、托盘与单实例

| ID | 技术设计要求 | 当前证据 | 状态 | 剩余验收 |
|---|---|---|---|---|
| W01 | 原生窗口 1440×900、最小 1024×700、浅色、系统标题栏 | `test_desktop_window.py` | 自动通过 | M03、M04、M08 |
| W02 | 强制 EdgeChromium，不回退 MSHTML | window contract、必需 DLL 检查 | 自动通过 | M07、M08 |
| W03 | WebView 数据持久化到 `webview` | `private_mode=False`、`storage_path` 测试 | 自动通过 | M08 重启持久性 |
| W04 | 外部链接交给系统浏览器 | pywebview setting contract | 自动通过 | M08 人工点击 |
| W05 | 后端 health 成功后才创建窗口 | controller readiness test | 自动通过 | M08 |
| W06 | 最小化隐藏到健康托盘 | controller 并发与降级测试 | 自动通过 | M08 |
| W07 | 关闭按钮默认隐藏到托盘 | controller close tests | 自动通过 | M08 |
| W08 | 托盘双击/默认项和菜单恢复 | tray menu + callback tests | 自动通过 | M08 |
| W09 | 托盘失败时不产生不可恢复隐藏 | startup/runtime tray loss tests | 自动通过 | M08 故障注入 |
| W10 | 托盘「退出」走统一完整关闭 | tray worker、controller cleanup tests | 自动通过 | M09 |
| W11 | shutdown 幂等且并发安全 | controller/single-instance 竞态测试 | 自动通过 | M09 |
| W12 | 第二实例不启动第二套后端 | Named Mutex 与入口测试 | 自动通过 | M08 双击实测 |
| W13 | 首次关闭到托盘显示一次提示 | 当前代码没有对应持久提示证据 | 未执行 | 需要实现或明确取消该建议 |
| W14 | 第二实例通过 named pipe 唤醒 | 技术设计列为后续增强 | 非首版范围 | 后续版本 |

### 5.3 路径、配置、数据库与日志

| ID | 技术设计要求 | 当前证据 | 状态 | 剩余验收 |
|---|---|---|---|---|
| D01 | 冻结可写数据统一在 `%LOCALAPPDATA%\ModWatcherAgent` | RuntimePaths tests；smoke 隔离数据 | 本机产物通过 | M05、M06 |
| D02 | bundle 资源只读、用户目录可写 | RuntimePaths 与 packaging 禁入测试 | 自动通过 | 受限账户 M06 |
| D03 | 环境变量在 backend imports 前注入 | desktop entry order test | 自动通过 | 无 |
| D04 | 桌面强制 `127.0.0.1`，禁止 LAN | RuntimePaths、security tests | 自动通过 | M11 网络观察 |
| D05 | 用户 `.env` 位于 `config\.env` | RuntimePaths/config integration | 自动通过 | M05 路径实测 |
| D06 | 新 DB 不存在时检查固定旧候选 | migration candidate tests | 自动通过 | M10 |
| D07 | SQLite Backup API 捕获 WAL | WAL migration test | 自动通过 | M10 真实库 |
| D08 | 完整 integrity、源库保留、失败不发布空库 | migration failure tests | 自动通过 | M10 |
| D09 | 并发迁移与非合作目标不被覆盖 | lock/no-clobber/primitive race tests | 自动通过 | M10 多进程人工补充可选 |
| D10 | 写入 `backups\migration.json` | metadata tests | 自动通过 | M10 查看真实记录 |
| D11 | 业务设置和通知配置保持兼容 | 现有 backend tests | 部分通过 | M12 |
| D12 | 桌面/崩溃日志写入用户目录 | logging tests；packaged smoke | 本机产物通过 | M08/M09 长时日志 |
| D13 | 日志脱敏 Authorization/密钥/Token/Webhook/Cookie/profile | `test_desktop_logging.py` | 自动通过 | 分享前人工复核仍必需 |
| D14 | `startup.log` 独立文件 | 当前实现主要使用 `desktop.log` 与 `crash.log` | 未执行 | 决定是否仍需要独立文件 |
| D15 | 缺失时把 bundle 游戏别名原子播种到 `config\game_aliases.json` | 首次播种、已有文件保护与发布碰撞测试；最终 onedir 含当前别名资源 | 自动通过 | 真实 GUI 功能见 M12 |
| D16 | smoke 退出恢复原有 `GAME_ALIAS_FILE`，原先未设时删除临时值 | 两态参数化 context 测试 | 自动通过 | 无 |

### 5.4 浏览器与安全

| ID | 技术设计要求 | 当前证据 | 状态 | 剩余验收 |
|---|---|---|---|---|
| B01 | 优先系统 Edge/Chrome，最后已安装 Chromium | browser launch choice tests | 自动通过 | M12 真实登录与实际回退顺序 |
| B02 | 冻结版不递归运行 Playwright CLI | frozen Chromium tests | 自动通过 | M12 |
| B03 | profile 与 snapshot 位于用户数据目录 | runtime integration + route tests | 自动通过 | M12 |
| B04 | WebView 主页面仅本地地址，第三方页面外置 | window setting、loopback tray validation | 自动通过 | M08/M12 |
| B05 | 保留 AccessPolicy | local-first/security tests | 自动通过 | M11 |
| B06 | Release 不含用户数据与秘密 | tree/ZIP/installer/workflow gates；最终 onedir/ZIP 禁入扫描 | 本机产物通过 | GitHub Release R04 再复验 |
| B07 | API Key 本地 SQLite 明文风险 | 设计明确保留兼容 | 部分通过 | 后续 DPAPI/Credential Manager |
| B08 | 随机桌面会话令牌 | 技术设计列为后续建议，当前无实现证据 | 非首版范围 | 后续安全版本 |

### 5.5 PyInstaller、portable 与安装器

| ID | 技术设计要求 | 当前证据 | 状态 | 剩余验收 |
|---|---|---|---|---|
| P01 | 打包前端、Alembic、别名、图标、README、LICENSE | spec 语义测试；最终 onedir 关键资源复验 | 本机产物通过 | GitHub Release R04 |
| P02 | 动态 imports 与无关 GUI backend 排除 | packaging contract | 自动通过 | 干净机 M01/M02 |
| P03 | `console=False`、版本资源、图标、不提权 | spec/version tests | 自动通过 | M01/M02 外观 |
| P04 | x64 PE 和 WebView2/pythonnet DLL | final x64 EXE；7 项关键资源；1,045 文件 | 本机产物通过 | GitHub-hosted R01/R04 |
| P05 | 清理/output/reparse/junction 边界 | packaging dynamic tests；最终 onedir/ZIP 禁入扫描 | 本机产物通过 | GitHub-hosted R01/R04 |
| P06 | portable ZIP 与同名 SHA256 | 81,104,020 bytes；摘要/文件名匹配；ZIP EXE 与 onedir 一致 | 本机产物通过 | GitHub Release R04 |
| P07 | 逐用户安装、开始菜单、可选桌面快捷方式 | 最终 Setup；静默逐用户自定义目录安装通过 | 部分通过 | 安装向导与快捷方式见 M06/M14 |
| P08 | WebView2 条件 Bootstrapper、签名、Unicode Exec、退出码复查 | resolver/identity/Inno contract tests | 静态通过 | M07、R02 |
| P09 | 卸载默认保留，交互双确认才删除 | Inno uninstall tests | 静态通过 | M14 |
| P10 | silent uninstall 保留数据 | contract；最终 Setup 静默卸载返回 0，sentinel 保留 | 本机产物通过 | GitHub-hosted/其他账户复验 |
| P11 | debug 构建开关/Debug EXE | 当前 `build_desktop.ps1` 没有 `-Debug` | 未执行 | 决定是否仍为首版要求 |
| P12 | Windows 代码签名 | 当前 EXE 与 Setup Authenticode 均为 `NotSigned` | 未执行 | 发布签名策略 |

### 5.6 CI/CD 与版本

| ID | 技术设计要求 | 当前证据 | 状态 | 剩余验收 |
|---|---|---|---|---|
| C01 | 只允许 workflow_dispatch 与 `v*` tag | workflow contract | 静态通过 | R01 |
| C02 | Windows Runner + Python 3.12 + Node 24 | workflow contract | 静态通过 | R01 |
| C03 | backend/frontend 质量门独立 fail-fast | workflow test | 静态通过 | R01 |
| C04 | 外部 Actions 固定完整 SHA，最小权限 | workflow test | 静态通过 | R01 |
| C05 | 官方 Inno 6.7.3、attestation、Authenticode | workflow test与官方校验流程 | 静态通过 | R02 |
| C06 | tag 与项目版本一致 | workflow test | 静态通过 | R04 |
| C07 | 精确 4 件资产与 SHA256 双阶段复验 | 动态正/负 workflow tests；最终本地 4 件资产及摘要复验 | 本机产物通过 | GitHub Release R04 |
| C08 | tag 创建或幂等更新 GitHub Release | workflow contract | 静态通过 | R04 |
| C09 | 单一版本源派生资产版本 | build 从 `backend/pyproject.toml` 读取；前端当前手工匹配 | 部分通过 | 自动同步前端版本可后续增强 |
| C10 | Inno 商业许可 | 仓库只记录政策，不授予许可 | 部分通过 | 商业发布者在 R02 前完成合规确认 |

### 5.7 功能、性能与后续范围

| ID | 技术设计要求 | 当前证据 | 状态 | 剩余验收 |
|---|---|---|---|---|
| F01 | Mod 列表、规则、收藏、更新 | backend/frontend 自动测试 | 部分通过 | M12 packaged GUI |
| F02 | AI 与 Telegram/Discord 兼容 | backend 自动测试 | 部分通过 | M12 使用真实或安全测试配置 |
| F03 | 窗口隐藏时 Scheduler 继续 | controller 与 lifespan 测试间接覆盖 | 部分通过 | M08/M12 长时观察 |
| F04 | 系统通知可用 | 现有业务能力，但无桌面人工证据 | 未执行 | M12 |
| F05 | 冷启动 ≤8 秒、热启动 ≤4 秒、恢复 ≤500 ms | 技术设计明确为目标，未测量 | 未执行 | M13 |
| F06 | 空闲内存 ≤250 MB、CPU 接近 0% | 未测量 | 未执行 | M13 |
| F07 | 正常退出 ≤10 秒 | 自动测试有超时边界，非性能测量 | 部分通过 | M13 |
| F08 | onefile、自动更新、Service、MSIX、跨平台桌面 | 技术设计明确排除 | 非首版范围 | 后续路线 |
| F09 | 冻结版开机启动写入带引号的绝对 EXE；源码模式保留 `start.ps1 -Tray` | autostart 精确命令测试 | 自动通过 | 真实 HKCU/登录启动见 M16 |

## 6. 远端验收矩阵

| ID | 场景 | 必须记录的证据 | 当前状态 |
|---|---|---|---|
| R01 | GitHub `workflow_dispatch` | run URL、commit SHA、所有 job/step 结果、artifact 清单 | 未执行 |
| R02 | GitHub Runner 真实 Inno | 6.7.3 下载/attestation/签名、ISCC 编译日志、Setup SHA256 | 未执行 |
| R03 | 当前桌面代码完整构建 | 基线 `5c10a62` 的 onedir smoke、portable、Setup、两个 SHA256，精确 4 件且内容 clean | 本机产物通过；GitHub-hosted 未执行 |
| R04 | `v<version>` tag Release | tag/version 匹配、publish job、Release URL、下载后 SHA256 复验 | 未执行 |

远端运行使用 Inno Setup 编译器前，商业发布者必须自行核对并取得符合 [Inno Setup 当前商业许可政策](https://jrsoftware.org/isorder.php) 的许可。本仓库不会授予或代替该许可。

## 7. Windows 人工验收矩阵

| ID | 场景 | 通过条件 | 当前状态 |
|---|---|---|---|
| M01 | Windows 10 22H2 x64 干净用户 | 无 Python/Node；安装/启动/退出成功；无静态资源 404 | 未执行 |
| M02 | Windows 11 当前稳定版 x64 干净用户 | 同 M01 | 未执行 |
| M03 | 100% / 125% / 150% DPI | 字体、缩放、标题栏、最小尺寸、菜单可用 | 未执行 |
| M04 | 单显示器 / 双显示器 | 隐藏、恢复、置前和切换显示器正常 | 未执行 |
| M05 | 中文用户名与含空格路径 | 安装、portable、数据、日志、迁移和 WebView 路径正常 | 部分通过：含中文/空格的静默安装目录；中文用户名与其余路径未执行 |
| M06 | 非管理员逐用户安装 | 安装到 LocalAppData；开始菜单/可选桌面快捷方式正常 | 部分通过：逐用户静默自定义目录安装；干净非管理员账户与快捷方式未执行 |
| M07 | WebView2 缺失 | 无 Bootstrapper时提示正确；有 Bootstrapper时成功/失败路径可操作 | 未执行 |
| M08 | 真实窗口和托盘 | 最小化/关闭隐藏、双击/菜单恢复、托盘故障降级 | 未执行 |
| M09 | 完整退出 | Scheduler/浏览器/后端/窗口/托盘关闭，进程和端口释放 | 部分通过：两次 headless smoke 进程/端口释放；GUI/浏览器/托盘未执行 |
| M10 | 真实旧 SQLite + WAL | 数据完整迁移、旧库保留、metadata 正确、失败不覆盖 | 未执行 |
| M11 | 无网络启动 | 已有依赖时本地 UI 可启动，后端只监听回环 | 未执行 |
| M12 | 功能回归 | Mod、规则、收藏、AI、通知、LoversLab 登录/抓取可用 | 未执行 |
| M13 | 性能 | 记录冷/热启动、恢复、退出、空闲内存与 CPU | 未执行 |
| M14 | 安装器生命周期 | 新装、覆盖升级、silent uninstall 保留、交互双确认删除 | 部分通过：静默新装/卸载与 sentinel 保留；升级和交互删除未执行 |
| M15 | SmartScreen/杀毒软件 | 记录 NotSigned 行为、误报、代码签名与声誉处理决定 | 未执行 |
| M16 | 冻结版开机启动 | 启用后 HKCU Run 指向当前绝对 EXE；重新登录可启动；关闭后删除；移动 portable 后重新启用可修正路径 | 未执行 |

## 8. 风险矩阵

| 风险 | 影响 | 当前缓解 | 残余风险 / 验收 |
|---|---:|---|---|
| PyInstaller 漏动态 import | 高 | hidden imports、required DLL、真实 backend smoke | smoke 不创建 GUI；M01/M02/M08 |
| Alembic 或前端资源漏包 | 高 | spec datas、contract、`/` 与 health smoke | 干净机升级 M01/M02/M14 |
| WebView2 缺失 | 高 | 原生错误、Inno 检测、可选签名 Bootstrapper | 当前 CI 不携带 Bootstrapper；M07/R02 |
| 托盘失败导致窗口丢失 | 高 | 实时健康、恢复与降级退出竞态测试 | 真实 shell/多屏 M04/M08 |
| 退出留下后端、线程或端口 | 高 | 幂等 cleanup、线程测试、packaged smoke | 长时任务/浏览器 M09/M12 |
| SQLite 迁移丢 WAL 或覆盖目标 | 高 | Backup API、integrity、锁、no-clobber、源库保留 | 真实旧库 M10 |
| 中文/空格路径失败 | 中 | pathlib/Unicode Exec、专项自动测试 | 实际 Windows 用户 M05 |
| 打包版 Chromium CLI 递归 | 中 | frozen 模式硬禁用，优先系统浏览器 | 系统浏览器缺失时功能不可用；M12 |
| Release 泄露数据库/密钥 | 高 | 多阶段 tree/ZIP/installer/CI 禁入扫描；当前 onedir/ZIP 已复验 | GitHub Release R04 再复验 |
| 日志泄露密钥/Cookie | 高 | 写入前脱敏与异常清理测试 | 新日志格式仍需 review；分享前人工检查 |
| API Key 明文存储 | 高 | 本机回环、用户目录和文档警示 | DPAPI/Credential Manager 未实现 |
| 端口 17500 被占用 | 中 | health 超时、原生错误与日志 | 正常模式不自动换端口；用户需释放 |
| SmartScreen/杀软误报 | 中 | onedir、版本资源、SHA256 | EXE 与 Setup 当前均 NotSigned；M15 |
| 当前 portable 与当前 onedir 不一致 | 高 | 已关闭：基线 `5c10a62` 完整重建；ZIP 内 EXE 与 onedir SHA256 一致 | 桌面代码再次变化后必须重建 |
| 游戏别名首次播种覆盖用户文件或留下半文件 | 高 | 目标目录临时文件、flush/fsync、原子 no-clobber 发布与竞态测试；最终 onedir 含当前资源 | 真实 GUI 功能 M12 |
| 移动 portable 后开机启动仍指向旧 EXE | 中 | HKCU Run 使用带引号绝对路径；用户指南要求移动后重新启用 | M16 |
| GitHub workflow 仅静态通过 | 高 | YAML/AST/动态契约测试、固定 SHA | 必须 R01/R04 真实执行 |
| Inno 商业许可不合规 | 高 | DEPENDENCIES/README 明示官方当前政策 | 商业发布者自行采购并留存记录 |
| 性能未达目标 | 中 | onedir、无 Vite、延迟浏览器 | M13 未执行 |

## 9. 发布放行条件

只有满足以下条件，才能把当前版本称为完成 Windows 独立客户端验收：

1. R01–R04 全部有可追溯证据。
2. M01–M14 与 M16 全部通过；M15 有明确签名/风险接受决定。
3. 当前桌面代码重新生成精确 4 件 Release 资产，不能复用旧 portable。（本机基线 `5c10a62` 已满足。）
4. 所有 SHA256 与对应资产双向匹配，最终资产禁入扫描通过。（本机资产已满足，GitHub Release 仍需复验。）
5. 当前版本全 backend、frontend 和桌面 focused tests 通过。（本机基线 `5c10a62` 已满足。）
6. 商业发布场景已完成 Inno Setup 当前许可合规确认。
7. Release notes 明确 WebView2、数据目录、卸载保留、备份和已知限制。

在这些条件全部完成前，文档可以使用「本机完整构建通过」「本机 4 件资产已复验」「静默安装生命周期部分通过」等有范围的表述，不应使用「Windows 10/11 已验收」「安装器全部路径已验证」或「GitHub Release 已成功发布」。
