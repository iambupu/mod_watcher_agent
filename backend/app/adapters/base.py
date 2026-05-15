import json
from abc import ABC, abstractmethod
from typing import Any

from app.models.mod_item import ModItem


class BaseAdapter(ABC):
    source: str
    adapters: dict[str, type["BaseAdapter"]] = {}

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if hasattr(cls, "source") and isinstance(cls.source, str) and cls.source:
            BaseAdapter.adapters[cls.source] = cls

    @abstractmethod
    async def fetch(self, source_config_json: str) -> list[ModItem]:
        config = json.loads(source_config_json)
        ...

    @abstractmethod
    async def fetch_mod_detail(
        self, external_id: str, game_domain: str | None = None
    ) -> ModItem | None:
        ...

    @abstractmethod
    def normalize(self, raw_item: dict) -> ModItem:
        ...
