# Mod Watcher Collector

Chrome MV3 扩展，用于把当前 Nexus Mods 或 LoversLab 的 Mod 页面保存到本地 Mod Watcher 数据库并加入收藏。

## 安装

1. 启动 Mod Watcher，并确认后端可通过 `http://127.0.0.1:17500` 访问。
2. 打开 `chrome://extensions`。
3. 启用「开发者模式」。
4. 点击「加载已解压的扩展程序」，选择这个 `chrome-extension` 目录。

## 使用

1. 打开支持的 Mod 页面：
   - `https://www.nexusmods.com/{game_domain}/mods/{mod_id}`
   - `https://www.loverslab.com/files/file/{file_id}-...`
2. 点击扩展图标。
3. 确认后端地址、游戏名、成人内容标记和可选备注。
4. 点击「收藏当前 Mod」。

如果 Mod Watcher 使用 `local_strict` 或 `shared_lan`，请在访问令牌字段填写配置好的 `MW_ADMIN_TOKEN`。令牌会保存在当前 Chrome 用户配置的本地扩展存储中。

扩展只保存公开元数据，不下载、不镜像、不绕过站点权限。
