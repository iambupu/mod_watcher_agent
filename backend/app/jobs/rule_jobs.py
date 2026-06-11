from sqlmodel import Session

from app.jobs.manual_jobs import create_job_run, enqueue_job_run
from app.models.watch_rule import WatchRule
from app.services.discovery_service import DiscoveryService


class RuleJobError(Exception):
    def __init__(self, status_code: int, detail: str):
        """保存可直接映射为 HTTP 响应的错误信息。"""
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def enqueue_rule_discovery(session: Session, rule_id: int) -> dict:
    """校验规则可运行后，创建并排队一次手动发现任务。"""
    rule = session.get(WatchRule, rule_id)
    if rule is None:
        raise RuleJobError(404, "Rule not found")
    if not rule.enabled:
        raise RuleJobError(400, "Rule is disabled")

    rule_name = rule.name
    bind = session.bind
    job = create_job_run(
        session,
        "run_rule_discovery",
        {"rule_id": rule_id, "rule_name": rule_name},
    )

    async def handler():
        """在独立会话中执行规则发现，避免复用请求事务。"""
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
