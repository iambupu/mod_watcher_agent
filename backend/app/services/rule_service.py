from datetime import UTC, datetime

from sqlalchemy import and_
from sqlmodel import Session, select

from app.models.watch_rule import WatchRule
from app.rule_constants import (
    DEFAULT_RULE_INTERVAL_MINUTES,
    MAX_RULE_INTERVAL_MINUTES,
    MIN_RULE_INTERVAL_MINUTES,
)
from app.schemas.watch_rule import (
    WatchRuleCreate,
    WatchRuleRead,
    WatchRuleUpdate,
    _validate_source_config_pair,
)
from app.utils.json import json_object
from app.utils.numeric import bounded_int


class RuleServiceError(Exception):
    def __init__(self, status_code: int, detail: str):
        """初始化实例并保存运行所需的依赖。"""
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def safe_interval_minutes(value: object) -> int:
    return bounded_int(
        value,
        default=DEFAULT_RULE_INTERVAL_MINUTES,
        minimum=MIN_RULE_INTERVAL_MINUTES,
        maximum=MAX_RULE_INTERVAL_MINUTES,
        default_when_below_minimum=True,
    )


def model_to_read(rule: WatchRule) -> WatchRuleRead:
    return WatchRuleRead(**_rule_payload(rule))


def _rule_payload(rule: WatchRule) -> dict:
    """构造前端和导入导出共用的规则 payload。"""
    return {
        "id": rule.id,
        "name": rule.name,
        "enabled": rule.enabled,
        "intervalMinutes": safe_interval_minutes(rule.interval_minutes),
        "source": rule.source,
        "sourceConfig": _stored_source_config(rule.source, rule.source_config_json),
        "filters": json_object(rule.filters_json),
        "notification": json_object(rule.notification_json),
        "created_at": rule.created_at,
        "updated_at": rule.updated_at,
    }


def rule_to_create_payload(rule: WatchRule) -> dict:
    payload = _rule_payload(rule)
    return {
        key: payload[key]
        for key in (
            "name",
            "enabled",
            "intervalMinutes",
            "source",
            "sourceConfig",
            "filters",
            "notification",
        )
    }


def _stored_source_config(source: str, raw: str | None) -> dict:
    parsed = json_object(raw)
    if parsed:
        return parsed
    if source == "loverslab":
        return {
            "gameLabel": "LoversLab",
            "accessMode": "rss",
            "feedUrls": ["https://www.loverslab.com/files/rss/"],
            "pageUrls": [],
            "maxItemsPerRun": 50,
            "updateDetection": "published_time",
        }
    return {
        "gameDomainName": "skyrimspecialedition",
        "updatedSinceDays": 7,
        "queryMode": "updated",
        "categoryNames": [],
        "tags": [],
        "sortBy": "updatedAt_desc",
    }


class RuleService:
    def __init__(self, session: Session):
        """初始化实例并保存运行所需的依赖。"""
        self.session = session

    def list_rules(
        self,
        *,
        source: str | None = None,
        enabled: bool | None = None,
        q: str | None = None,
    ) -> list[WatchRuleRead]:
        """查询并返回列表数据。"""
        stmt = select(WatchRule)
        conditions = []
        if source is not None:
            conditions.append(WatchRule.source == source)
        if enabled is not None:
            conditions.append(WatchRule.enabled == enabled)
        if q is not None:
            conditions.append(WatchRule.name.icontains(q))
        if conditions:
            stmt = stmt.where(and_(*conditions))
        return [model_to_read(rule) for rule in self.session.exec(stmt).all()]

    def export_rules(self) -> dict:
        rules = self.session.exec(select(WatchRule)).all()
        return {
            "version": 1,
            "exportedAt": datetime.now(UTC).isoformat(),
            "rules": [rule_to_create_payload(rule) for rule in rules],
        }

    def import_rules(self, raw_rules: list[dict], *, commit: bool = True) -> dict:
        imported = 0
        skipped = 0
        for item in raw_rules:
            if not isinstance(item, dict):
                skipped += 1
                continue
            try:
                validated = WatchRuleCreate.model_validate(item)
            except Exception:
                skipped += 1
                continue

            existing = self.session.exec(
                select(WatchRule).where(
                    WatchRule.name == validated.name,
                    WatchRule.source == validated.source,
                )
            ).first()
            now = datetime.now(UTC).isoformat()
            if existing:
                existing.enabled = validated.enabled
                existing.interval_minutes = safe_interval_minutes(validated.intervalMinutes)
                existing.source_config_json = validated.sourceConfig.model_dump_json()
                existing.filters_json = validated.filters.model_dump_json()
                existing.notification_json = validated.notification.model_dump_json()
                existing.updated_at = now
                self.session.add(existing)
            else:
                self.session.add(
                    WatchRule(
                        name=validated.name,
                        enabled=validated.enabled,
                        interval_minutes=safe_interval_minutes(validated.intervalMinutes),
                        source=validated.source,
                        source_config_json=validated.sourceConfig.model_dump_json(),
                        filters_json=validated.filters.model_dump_json(),
                        notification_json=validated.notification.model_dump_json(),
                        created_at=now,
                        updated_at=now,
                    )
                )
            imported += 1
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        return {"imported": imported, "skipped": skipped}

    def get_rule(self, rule_id: int) -> WatchRule:
        rule = self.session.get(WatchRule, rule_id)
        if rule is None:
            raise RuleServiceError(404, "Rule not found")
        return rule

    def get_rule_read(self, rule_id: int) -> WatchRuleRead:
        return model_to_read(self.get_rule(rule_id))

    def create_rule(self, data: WatchRuleCreate, *, commit: bool = True) -> WatchRuleRead:
        """创建并持久化对应的数据。"""
        now = datetime.now(UTC).isoformat()
        rule = WatchRule(
            name=data.name,
            enabled=data.enabled,
            interval_minutes=safe_interval_minutes(data.intervalMinutes),
            source=data.source,
            source_config_json=data.sourceConfig.model_dump_json(),
            filters_json=data.filters.model_dump_json(),
            notification_json=data.notification.model_dump_json(),
            created_at=now,
            updated_at=now,
        )
        self.session.add(rule)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        self.session.refresh(rule)
        return model_to_read(rule)

    def update_rule(self, rule_id: int, data: WatchRuleUpdate, *, commit: bool = True) -> WatchRuleRead:
        """更新已有数据并返回结果。"""
        rule = self.get_rule(rule_id)
        if data.source is not None and data.source != rule.source:
            raise RuleServiceError(422, "Source field is immutable")

        if data.name is not None:
            rule.name = data.name
        if data.enabled is not None:
            rule.enabled = data.enabled
        if data.intervalMinutes is not None:
            rule.interval_minutes = safe_interval_minutes(data.intervalMinutes)
        if data.sourceConfig is not None:
            try:
                _validate_source_config_pair(rule.source, data.sourceConfig)
            except ValueError as exc:
                raise RuleServiceError(422, str(exc)) from exc
            rule.source_config_json = data.sourceConfig.model_dump_json()
        if data.filters is not None:
            rule.filters_json = data.filters.model_dump_json()
        if data.notification is not None:
            rule.notification_json = data.notification.model_dump_json()

        rule.updated_at = datetime.now(UTC).isoformat()
        self.session.add(rule)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
        self.session.refresh(rule)
        return model_to_read(rule)

    def delete_rule(self, rule_id: int, *, commit: bool = True) -> None:
        """删除对应数据并返回处理结果。"""
        rule = self.get_rule(rule_id)
        self.session.delete(rule)
        if commit:
            self.session.commit()
        else:
            self.session.flush()
