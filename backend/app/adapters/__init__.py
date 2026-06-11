# 中文注释：标记 adapters 包，保证后端模块可以按包路径导入。

from app.adapters.loverslab import LoversLabAdapter
from app.adapters.nexusmods import NexusModsAdapter

__all__ = ["NexusModsAdapter", "LoversLabAdapter"]
