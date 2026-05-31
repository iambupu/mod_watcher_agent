from abc import ABC, abstractmethod
from typing import Any, ClassVar

from app.models.mod_item import ModItem


class BaseAdapter(ABC):
    source: str
    adapters: ClassVar[dict[str, type["BaseAdapter"]]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "source") and isinstance(cls.source, str) and cls.source:
            BaseAdapter.adapters[cls.source] = cls

    @abstractmethod
    async def fetch(self, source_config_json: str) -> list[ModItem]:
        """请求外部数据并返回标准化结果。"""
        ...

    @abstractmethod
    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        """请求外部数据并返回标准化结果。"""
        ...

    @abstractmethod
    def normalize(self, raw_item: dict) -> ModItem:
        """规范化输入数据，供后续流程使用。"""
        ...
