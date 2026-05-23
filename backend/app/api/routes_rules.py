import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlmodel import Session

from app.db import get_session
from app.jobs.rule_jobs import RuleJobError, enqueue_rule_discovery
from app.jobs.scheduler import register_jobs
from app.schemas.watch_rule import (
    RuleTestRequest,
    RuleTestResponse,
    WatchRuleCreate,
    WatchRuleRead,
    WatchRuleUpdate,
)
from app.services.rule_import_service import (
    RuleImportError,
    import_rules_payload_from_url,
    require_public_host,
)
from app.services.rule_service import RuleService, RuleServiceError
from app.services.rule_test_service import RuleTestService, RuleTestServiceError

router = APIRouter(prefix="/api/rules", tags=["rules"])

_require_public_host = require_public_host


def _raise_http_error(exc: RuleServiceError | RuleImportError | RuleTestServiceError | RuleJobError) -> None:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    raise HTTPException(status_code=exc.status_code, detail=exc.detail)


@router.get("", response_model=list[WatchRuleRead])
def list_rules(
    source: str | None = Query(default=None),
    enabled: bool | None = Query(default=None),
    q: str | None = Query(default=None),
    session: Session = Depends(get_session),
):
    """查询并返回列表数据。"""
    return RuleService(session).list_rules(source=source, enabled=enabled, q=q)


@router.get("/export")
def export_rules(session: Session = Depends(get_session)):
    """处理当前模块的业务逻辑并返回结果。"""
    return RuleService(session).export_rules()


@router.post("/import")
def import_rules(
    body: dict,
    session: Session = Depends(get_session),
):
    """处理当前模块的业务逻辑并返回结果。"""
    raw_rules = body.get("rules")
    if not isinstance(raw_rules, list):
        url = str(body.get("url") or "").strip()
        if not url:
            raise HTTPException(status_code=422, detail="Provide either rules array or import URL")
        try:
            raw_rules = import_rules_payload_from_url(
                url,
                client_factory=httpx.Client,
                public_host_checker=_require_public_host,
            )
        except RuleImportError as exc:
            _raise_http_error(exc)

    result = RuleService(session).import_rules(raw_rules)
    register_jobs(session)
    return result


@router.get("/{rule_id}", response_model=WatchRuleRead)
def get_rule(rule_id: int, session: Session = Depends(get_session)):
    """读取并返回对应的数据。"""
    try:
        return RuleService(session).get_rule_read(rule_id)
    except RuleServiceError as exc:
        _raise_http_error(exc)


@router.post("", response_model=WatchRuleRead, status_code=201)
def create_rule(
    data: WatchRuleCreate,
    session: Session = Depends(get_session),
):
    """创建并持久化对应的数据。"""
    result = RuleService(session).create_rule(data)
    register_jobs(session)
    return result


@router.patch("/{rule_id}", response_model=WatchRuleRead)
def update_rule(
    rule_id: int,
    data: WatchRuleUpdate,
    session: Session = Depends(get_session),
):
    """更新已有数据并返回结果。"""
    try:
        result = RuleService(session).update_rule(rule_id, data)
    except RuleServiceError as exc:
        _raise_http_error(exc)
    register_jobs(session)
    return result


@router.delete("/{rule_id}", status_code=204)
def delete_rule(rule_id: int, session: Session = Depends(get_session)):
    """删除对应数据并返回处理结果。"""
    try:
        RuleService(session).delete_rule(rule_id)
    except RuleServiceError as exc:
        _raise_http_error(exc)
    register_jobs(session)
    return Response(status_code=204)


@router.post("/test", response_model=RuleTestResponse)
async def test_rule(
    body: RuleTestRequest,
    session: Session = Depends(get_session),
):
    """处理当前模块的业务逻辑并返回结果。"""
    try:
        return await RuleTestService(session).test_rule(body)
    except RuleTestServiceError as exc:
        _raise_http_error(exc)


@router.post("/{rule_id}/run", status_code=status.HTTP_202_ACCEPTED)
async def run_rule_discovery(
    rule_id: int,
    session: Session = Depends(get_session),
):
    """执行任务流程并返回结果。"""
    try:
        return enqueue_rule_discovery(session, rule_id)
    except RuleJobError as exc:
        _raise_http_error(exc)
