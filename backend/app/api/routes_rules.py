import json
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import and_
from sqlmodel import Session, select

from app.adapters.base import BaseAdapter
from app.db import get_session
from app.jobs.manual_jobs import create_job_run, enqueue_job_run
from app.jobs.scheduler import register_jobs
from app.models.watch_rule import WatchRule
from app.schemas.watch_rule import (
    RuleTestRequest,
    RuleTestResponse,
    WatchRuleCreate,
    WatchRuleRead,
    WatchRuleUpdate,
)
from app.services.discovery_service import DiscoveryService, _mod_item_to_dict
from app.services.filter_service import FilterService
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/rules", tags=["rules"])

logger = logging.getLogger(__name__)


def _model_to_read(rule: WatchRule) -> WatchRuleRead:
    return WatchRuleRead(
        id=rule.id,
        name=rule.name,
        enabled=rule.enabled,
        intervalMinutes=rule.interval_minutes or 360,
        source=rule.source,
        sourceConfig=json.loads(rule.source_config_json),
        filters=json.loads(rule.filters_json),
        notification=json.loads(rule.notification_json),
        created_at=rule.created_at,
        updated_at=rule.updated_at,
    )


@router.get("", response_model=list[WatchRuleRead])
def list_rules(
    source: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
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
    results = session.exec(stmt).all()
    return [_model_to_read(r) for r in results]


@router.get("/{rule_id}", response_model=WatchRuleRead)
def get_rule(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(WatchRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return _model_to_read(rule)


@router.post("", response_model=WatchRuleRead, status_code=201)
def create_rule(
    data: WatchRuleCreate,
    session: Session = Depends(get_session),
):
    now = datetime.now(timezone.utc).isoformat()
    rule = WatchRule(
        name=data.name,
        enabled=data.enabled,
        interval_minutes=data.intervalMinutes,
        source=data.source,
        source_config_json=data.sourceConfig.model_dump_json(),
        filters_json=data.filters.model_dump_json(),
        notification_json=data.notification.model_dump_json(),
        created_at=now,
        updated_at=now,
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    register_jobs(session)
    return _model_to_read(rule)


@router.patch("/{rule_id}", response_model=WatchRuleRead)
def update_rule(
    rule_id: int,
    data: WatchRuleUpdate,
    session: Session = Depends(get_session),
):
    rule = session.get(WatchRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")

    if data.source is not None and data.source != rule.source:
        raise HTTPException(status_code=422, detail="Source field is immutable")

    if data.name is not None:
        rule.name = data.name
    if data.enabled is not None:
        rule.enabled = data.enabled
    if data.intervalMinutes is not None:
        rule.interval_minutes = data.intervalMinutes
    if data.sourceConfig is not None:
        rule.source_config_json = data.sourceConfig.model_dump_json()
    if data.filters is not None:
        rule.filters_json = data.filters.model_dump_json()
    if data.notification is not None:
        rule.notification_json = data.notification.model_dump_json()

    rule.updated_at = datetime.now(timezone.utc).isoformat()
    session.add(rule)
    session.commit()
    session.refresh(rule)
    register_jobs(session)
    return _model_to_read(rule)


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    rule = session.get(WatchRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    session.delete(rule)
    session.commit()
    register_jobs(session)
    return Response(status_code=204)


@router.post("/test", response_model=RuleTestResponse)
async def test_rule(
    body: RuleTestRequest,
    session: Session = Depends(get_session),
):
    rule_data = body.rule
    AdapterClass = BaseAdapter.adapters.get(rule_data.source)
    if AdapterClass is None:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown source '{rule_data.source}'",
        )

    nexus_api_key = (
        SettingsService(session).get("nexus_api_key")
        if rule_data.source == "nexusmods"
        else ""
    )
    adapter = (
        AdapterClass(api_key=nexus_api_key or "")
        if rule_data.source == "nexusmods"
        else AdapterClass()
    )
    source_config_json = rule_data.sourceConfig.model_dump_json()
    filters_json = rule_data.filters.model_dump_json()
    notification_json = rule_data.notification.model_dump_json()
    now = datetime.now(timezone.utc).isoformat()
    preview_rule = WatchRule(
        name=rule_data.name,
        enabled=rule_data.enabled,
        interval_minutes=rule_data.intervalMinutes,
        source=rule_data.source,
        source_config_json=source_config_json,
        filters_json=filters_json,
        notification_json=notification_json,
        created_at=now,
        updated_at=now,
    )

    try:
        raw_items = await adapter.fetch(source_config_json)
    except Exception as e:
        logger.exception("Rule test failed for source %s", rule_data.source)
        raise HTTPException(status_code=502, detail=str(e)) from e

    all_mods = [_mod_item_to_dict(item) for item in raw_items]
    filtered_items = FilterService().apply_filters(preview_rule, all_mods, session)
    scanned = len(raw_items)
    normalized = len(all_mods)
    passed_deterministic = len(filtered_items)

    response = RuleTestResponse(
        scanned=scanned,
        normalized=normalized,
        passedDeterministicFilters=passed_deterministic,
        passedLlmFilters=passed_deterministic,
        rejectedReasons={
            "filtered": max(0, normalized - passed_deterministic),
        },
        items=filtered_items[:20],
    )
    return response


@router.post("/{rule_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_rule_discovery(
    rule_id: int,
    session: Session = Depends(get_session),
):
    rule = session.get(WatchRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    if not rule.enabled:
        raise HTTPException(status_code=400, detail="Rule is disabled")

    rule_name = rule.name
    bind = session.bind
    job = create_job_run(
        session,
        "run_rule_discovery",
        {"rule_id": rule_id, "rule_name": rule_name},
    )

    async def handler():
        with Session(bind) as job_session:
            discovery = DiscoveryService(job_session)
            new_mods = await discovery.discover_from_rule(rule_id)
            return {
                "rule_id": rule_id,
                "rule_name": rule_name,
                "newMods": len(new_mods),
                "items_scanned": 1,
                "items_matched": len(new_mods),
            }

    enqueue_job_run(job.id, handler)
    return {"status": "queued", "job_id": job.id}
