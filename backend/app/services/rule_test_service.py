import json
import logging
from datetime import UTC, datetime

from sqlmodel import Session

from app.adapters.base import BaseAdapter
from app.models.watch_rule import WatchRule
from app.schemas.watch_rule import RuleTestRequest, RuleTestResponse
from app.services.discovery_service import _mod_item_to_dict
from app.services.filter_service import FilterService
from app.services.llm_client import create_llm_filter_client
from app.services.settings_service import SettingsService

logger = logging.getLogger(__name__)


class RuleTestServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        """初始化实例并保存运行所需的依赖。"""
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class RuleTestService:
    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    async def test_rule(self, body: RuleTestRequest) -> RuleTestResponse:
        """处理当前模块的业务逻辑并返回结果。"""
        rule_data = body.rule
        adapter_class = BaseAdapter.adapters.get(rule_data.source)
        if adapter_class is None:
            raise RuleTestServiceError(422, f"Unknown source '{rule_data.source}'")

        nexus_api_key = (
            SettingsService(self.session).get("nexus_api_key")
            if rule_data.source == "nexusmods"
            else ""
        )
        adapter = (
            adapter_class(api_key=nexus_api_key or "")
            if rule_data.source == "nexusmods"
            else adapter_class()
        )
        source_config_json = rule_data.sourceConfig.model_dump_json()
        preview_rule = WatchRule(
            name=rule_data.name,
            enabled=rule_data.enabled,
            interval_minutes=rule_data.intervalMinutes,
            source=rule_data.source,
            source_config_json=source_config_json,
            filters_json=rule_data.filters.model_dump_json(),
            notification_json=rule_data.notification.model_dump_json(),
            created_at=datetime.now(UTC).isoformat(),
            updated_at=datetime.now(UTC).isoformat(),
        )

        try:
            raw_items = await adapter.fetch(source_config_json)
        except Exception as exc:
            logger.exception("Rule test failed for source %s", rule_data.source)
            raise RuleTestServiceError(502, str(exc)) from exc

        all_mods = [_mod_item_to_dict(item) for item in raw_items]
        filter_service = FilterService(llm_client=create_llm_filter_client(self.session))
        filtered_items = filter_service.apply_filters(preview_rule, all_mods, self.session)
        response = RuleTestResponse(
            scanned=len(raw_items),
            normalized=len(all_mods),
            passedDeterministicFilters=filter_service.stats["passed_deterministic"],
            passedLlmFilters=filter_service.stats["passed_llm"],
            rejectedReasons=filter_service.rejected_reasons,
            rejectedItems=filter_service.rejected_items[:100],
            items=getattr(filter_service, "preview_items_before_deduplicate", filtered_items)[:20],
        )
        if filter_service.rejected_items:
            logger.info(
                "Rule test rejected items for '%s': %s",
                rule_data.name,
                json.dumps(filter_service.rejected_items[:100], ensure_ascii=False),
            )
        return response
