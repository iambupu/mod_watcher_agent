# 依赖与发布工具链

本项目包含源码运行、Windows 独立客户端构建和前端构建 3 类依赖。普通用户使用安装版或便携版时，不需要自行安装 Python、Node.js 或 npm。

## 普通用户运行要求

- Windows 10/11 x64。
- Microsoft Edge WebView2 Runtime，用于独立应用窗口。
- 系统 Microsoft Edge 或 Google Chrome，用于 LoversLab 登录和抓取；如果机器已经安装 Playwright Chromium，也可作为最后回退。
- 足够的当前用户目录写权限，用于 `%LOCALAPPDATA%\ModWatcherAgent`。

PyInstaller onedir 会随应用分发 Python 解释器、后端依赖、React 静态资源、Alembic 资源、pywebview、pystray、Pillow 和所需 .NET/WebView2 loader 文件。

打包版明确禁用从主 EXE 内执行 Playwright Chromium 安装命令。浏览器缺失时应安装系统 Edge 或 Chrome，不要尝试对 `ModWatcherAgent.exe` 运行 Python 模块参数。

## 后端依赖

权威清单：`backend/pyproject.toml`。

运行依赖位于 `[project].dependencies`，要求 Python 3.11+：

```powershell
python -m pip install -e .\backend
```

开发与测试依赖：

```powershell
python -m pip install -e ".\backend[dev]"
```

桌面运行依赖：

```powershell
python -m pip install -e ".\backend[desktop]"
```

其中桌面 extra 当前包含：

- `pywebview>=6.0,<7`
- `pystray>=0.19.5`
- `Pillow>=10`

打包工具：

```powershell
python -m pip install -e ".\backend[packaging]"
```

`packaging` extra 把 PyInstaller 限制为 `>=6,<7`。完整桌面构建通常一次安装：

```powershell
python -m pip install -e ".\backend[dev,desktop,packaging]"
```

## 前端依赖

权威清单：

- `frontend/package.json`
- `frontend/package-lock.json`

前端声明 Node.js 18+；GitHub Actions 发布链固定使用 Node.js 24 和 `npm ci`。

```powershell
cd frontend
npm ci
npm run typecheck
npm test
npm run build
```

生产客户端使用 `frontend/dist`，不会启动 Vite，也不要求用户机器安装 Node.js。

## Windows 打包工具

桌面构建入口为 `scripts/build_desktop.ps1`，目标是 Windows x64 onedir。脚本会拒绝非 Windows、非 64 位 Python 和非 `Machine=0x8664` 的 PE 输出。

主要工具链：

| 工具 | 本地/CI 约束 | 用途 |
|---|---|---|
| Python | 3.11+；CI 使用 3.12 | 后端、测试、PyInstaller |
| Node.js | 18+；CI 使用 24 | 前端 typecheck、test、build |
| PyInstaller | `>=6,<7` | 生成 `dist-desktop\ModWatcherAgent` onedir |
| PowerShell | Windows PowerShell/pwsh | 构建、smoke、portable 与 SHA256 |
| Inno Setup | CI 固定 6.7.3 | 生成逐用户安装器 |

完整本地构建：

```powershell
.\scripts\build_desktop.ps1
```

如果本机没有 `ISCC.exe`：

```powershell
.\scripts\build_desktop.ps1 -SkipInstaller
```

生成的主要资产：

```text
release\ModWatcherAgent-<version>-win-x64-portable.zip
release\ModWatcherAgent-<version>-win-x64-portable.zip.sha256
release\ModWatcherAgent-Setup-<version>-win-x64.exe
release\ModWatcherAgent-Setup-<version>-win-x64.exe.sha256
```

构建脚本会扫描 onedir、portable staging 和 ZIP，拒绝 `.env*`、SQLite 数据库及派生文件、日志、浏览器 profile、快照、缓存、测试目录和明显的密钥/凭据文件。

## Inno Setup 许可与来源验证

商业环境使用 Inno Setup IDE、编译器或由 CI 调用编译器时，组织或发布者必须自行核对并取得符合 [Inno Setup 当前商业许可政策](https://jrsoftware.org/isorder.php) 的许可。官方政策把 CI 中无人值守调用编译器也计入使用场景；本仓库、开源许可证、GitHub Actions 配置和已生成的安装器都不会替使用者授予 Inno Setup 商业许可。

当前 workflow 从官方 `jrsoftware/issrc` 不可变 tag `is-6_7_3` 下载 `innosetup-6.7.3.exe`，并执行：

1. `gh release verify-asset` 验证 GitHub artifact attestation。
2. Authenticode 状态必须为 `Valid`。
3. 签名者必须匹配 `Pyrsys B.V.`。
4. 使用 `/CURRENTUSER` 静默安装到 Runner 临时目录。

验证方法与发布者信息以 [Inno Setup 官方下载验证说明](https://jrsoftware.org/isdl-verify.php) 为准。

这段 workflow 已通过本地 YAML、PowerShell AST 和契约测试，但 GitHub-hosted Runner 上的实际下载、安装、编译与发布仍属于远端验收，不应写成已执行成功。

## WebView2 Bootstrapper

安装器只会在构建者显式提供 `MicrosoftEdgeWebview2Setup.exe` 时尝试编入 Bootstrapper。构建脚本要求：

- 文件名匹配。
- Microsoft Authenticode 签名有效。
- 签名证书组织为 `Microsoft Corporation`。
- 签名覆盖的版本资源符合已知 Evergreen Bootstrapper 组合。

安装命令为 Microsoft 文档指定的 `/silent /install`。更多信息见 [WebView2 Runtime 分发指南](https://learn.microsoft.com/en-us/microsoft-edge/webview2/concepts/distribution)。

## 版本基线

- 项目版本权威源：`backend/pyproject.toml`。
- 当前项目版本：`0.2.2`。
- 前端 `package.json` 应与发布版本保持一致。
- Windows FileVersion、安装器版本和资产文件名由构建链从项目版本派生。
- Git tag 必须严格匹配 `v<project-version>`，否则发布 workflow 失败。

## 相关文档

- [Windows 桌面客户端指南](./docs/desktop-client.md)
- [桌面客户端验收记录](./docs/desktop-client-acceptance.md)
- [Windows 桌面客户端技术设计](./docs/desktop-client-technical-design.md)
