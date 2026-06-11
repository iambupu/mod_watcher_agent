from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.models.mod_item import ModItem


class BaseAdapter(ABC):
    source: str
    adapters: ClassVar[dict[str, type["BaseAdapter"]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """子类声明 source 后自动注册，供发现任务按来源分发适配器。"""
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "source") and isinstance(cls.source, str) and cls.source:
            BaseAdapter.adapters[cls.source] = cls

    @abstractmethod
    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """根据规则配置抓取一批远端 Mod，并返回统一 ModItem。"""
        ...

    @abstractmethod
    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """按来源身份查询单个 Mod 详情；无法恢复时返回 None。"""
        ...

    @abstractmethod
    def normalize(self, raw_item: dict) -> ModItem:
        """把来源原始结构转换为服务层可消费的 ModItem。"""
        ...

    async def aclose(self) -> None:
        """Close HTTP clients or other resources held by this adapter."""
        return None
