import json
import logging
import concurrent.futures
import socket
from datetime import datetime, timezone
from ipaddress import ip_address
from urllib.parse import urlparse

import httpx
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
from app.services.llm_client import create_llm_filter_client
from app.services.settings_service import SettingsService

router = APIRouter(prefix="/api/rules", tags=["rules"])

logger = logging.getLogger(__name__)
DEFAULT_RULE_INTERVAL_MINUTES = 360


def _safe_interval_minutes(value: int | None) -> int:
    if value is None:
        return DEFAULT_RULE_INTERVAL_MINUTES
    if value < 1:
        return DEFAULT_RULE_INTERVAL_MINUTES
    return value


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


def _rule_to_create_payload(rule: WatchRule) -> dict:
    return {
        "name": rule.name,
        "enabled": rule.enabled,
        "intervalMinutes": rule.interval_minutes or 360,
        "source": rule.source,
        "sourceConfig": json.loads(rule.source_config_json),
        "filters": json.loads(rule.filters_json),
        "notification": json.loads(rule.notification_json),
    }


def _import_rules_payload_from_url(url: str) -> list[dict]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=422, detail="Only http/https URLs are allowed")

    # SSRF guard: resolve host and reject private / loopback / link-local IPs.
    _require_public_host(parsed.hostname)

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Failed to fetch rules from URL: {exc}") from exc

    # Re-check the final URL after redirects.
    if str(resp.url) != url:
        final = urlparse(str(resp.url))
        _require_public_host(final.hostname)

    try:
        data = resp.json()
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="URL response is not valid JSON") from exc
    if isinstance(data, dict) and isinstance(data.get("rules"), list):
        return data["rules"]
    if isinstance(data, list):
        return data
    raise HTTPException(status_code=422, detail="Imported JSON must be an array or {\"rules\": [...]}")


def _require_public_host(hostname: str | None) -> None:
    if not hostname:
        raise HTTPException(status_code=422, detail="URL must include a hostname")
    try:
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future = executor.submit(socket.getaddrinfo, hostname, None)
            addrs = future.result(timeout=30.0)
    except (socket.gaierror, concurrent.futures.TimeoutError, ValueError):
        raise HTTPException(status_code=422, detail="Unable to resolve host")
    for _family, _type, _proto, _name, sockaddr in addrs:
        try:
            ip = ip_address(sockaddr[0])
        except ValueError:
            continue
        if ip.is_loopback or ip.is_private or ip.is_link_local:
            raise HTTPException(status_code=422, detail="Private or loopback hosts are not allowed")


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


@router.get("/export")
def export_rules(session: Session = Depends(get_session)):
    rules = session.exec(select(WatchRule)).all()
    payload = {
        "version": 1,
        "exportedAt": datetime.now(timezone.utc).isoformat(),
        "rules": [_rule_to_create_payload(rule) for rule in rules],
    }
    return payload


@router.post("/import")
def import_rules(
    body: dict,
    session: Session = Depends(get_session),
):
    raw_rules = body.get("rules")
    if not isinstance(raw_rules, list):
        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="Provide either rules array or import URL")
        raw_rules = _import_rules_payload_from_url(url)

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
        existing = session.exec(
            select(WatchRule).where(
                WatchRule.name == validated.name,
                WatchRule.source == validated.source,
            )
        ).first()
        now = datetime.now(timezone.utc).isoformat()
        if existing:
            existing.enabled = validated.enabled
            existing.interval_minutes = _safe_interval_minutes(validated.intervalMinutes)
            existing.source_config_json = validated.sourceConfig.model_dump_json()
            existing.filters_json = validated.filters.model_dump_json()
            existing.notification_json = validated.notification.model_dump_json()
            existing.updated_at = now
            session.add(existing)
        else:
            session.add(
                WatchRule(
                    name=validated.name,
                    enabled=validated.enabled,
                    interval_minutes=_safe_interval_minutes(validated.intervalMinutes),
                    source=validated.source,
                    source_config_json=validated.sourceConfig.model_dump_json(),
                    filters_json=validated.filters.model_dump_json(),
                    notification_json=validated.notification.model_dump_json(),
                    created_at=now,
                    updated_at=now,
                )
            )
        imported += 1
    session.commit()
    register_jobs(session)
    return {"imported": imported, "skipped": skipped}


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
        interval_minutes=_safe_interval_minutes(data.intervalMinutes),
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
        rule.interval_minutes = _safe_interval_minutes(data.intervalMinutes)
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
    filter_service = FilterService(llm_client=create_llm_filter_client(session))
    filtered_items = filter_service.apply_filters(preview_rule, all_mods, session)
    scanned = len(raw_items)
    normalized = len(all_mods)

    response = RuleTestResponse(
        scanned=scanned,
        normalized=normalized,
        passedDeterministicFilters=filter_service.stats["passed_deterministic"],
        passedLlmFilters=filter_service.stats["passed_llm"],
        rejectedReasons=filter_service.rejected_reasons,
        rejectedItems=filter_service.rejected_items[:100],
        items=filtered_items[:20],
    )
    if filter_service.rejected_items:
        logger.info(
            "Rule test rejected items for '%s': %s",
            rule_data.name,
            json.dumps(filter_service.rejected_items[:100], ensure_ascii=False),
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
