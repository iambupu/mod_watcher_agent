# Mod Watcher Agent Windows 桌面版发布说明

## 运行要求

- 支持 Windows 10/11 x64；普通用户不需要安装 Python 或 Node.js。
- 独立窗口需要 Microsoft Edge WebView2 Runtime。缺失时请从 Microsoft 官方 WebView2 页面安装后重试。

## 数据、卸载与备份

- 数据库、配置、日志、浏览器资料和快照位于 `%LOCALAPPDATA%\ModWatcherAgent`，升级不会覆盖该目录。
- 卸载默认保留用户数据；静默卸载始终保留。交互卸载只有在连续两次确认后才删除数据。
- 升级、重装或手工重置前，请完整退出客户端并备份 `%LOCALAPPDATA%\ModWatcherAgent`，至少保留 `data` 与 `config` 子目录。

## 已知限制

- 当前 EXE 与安装器未进行商业代码签名，Windows 属性可能显示 `NotSigned`，SmartScreen 或杀毒软件可能提示未知发布者。
- Windows 10/11 完整 GUI、DPI/双屏、托盘长时运行、缺失 WebView2、覆盖升级和交互卸载仍需按验收矩阵复核。
- 安装包不内置 Playwright Chromium；LoversLab 浏览器功能优先使用系统 Edge 或 Chrome。
