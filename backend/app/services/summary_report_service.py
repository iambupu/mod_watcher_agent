from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlmodel import Session, func, select

from app.models.mod import Mod
from app.services.llm_client import create_llm_client
from app.services.llm_provider_config import (
    get_provider_chain,
    provider_config_has_credentials,
    resolve_provider_config,
)
from app.services.settings_service import SettingsService
from app.services.system_notification_service import SystemNotificationService

REPORT_LANGUAGE_NAMES = {
    "zh-CN": "简体中文",
    "en-US": "English",
    "ja-JP": "日本語",
}
MIN_SCHEDULED_WINDOW_MINUTES = 360


def summary_window_minutes(interval_minutes: int, *, force: bool) -> int:
    """处理当前模块的业务逻辑并返回结果。"""
    if interval_minutes > 0:
        return max(interval_minutes, MIN_SCHEDULED_WINDOW_MINUTES)
    return 10080 if force else 0


async def generate_summary_report_payload(
    session: Session,
    *,
    force: bool = False,
    create_client: Callable[[str, str, str | None], Any] = create_llm_client,
) -> dict:
    """处理当前模块的业务逻辑并返回结果。"""
    settings_svc = SettingsService(session)
    interval = int(settings_svc.get("summary_report_interval_minutes") or "0")
    prompt_focus = (settings_svc.get("summary_report_prompt") or "").strip()
    ui_language = settings_svc.get("ui_language") or "zh-CN"
    output_language = REPORT_LANGUAGE_NAMES.get(ui_language, ui_language)
    if not prompt_focus:
        return {"generated": False, "reason": "missing_prompt", "items_scanned": 0, "items_matched": 0}

    window_minutes = summary_window_minutes(interval, force=force)
    if window_minutes <= 0:
        return {"generated": False, "reason": "disabled", "items_scanned": 0, "items_matched": 0}

    since = datetime.now(UTC) - timedelta(minutes=window_minutes)
    mods = session.exec(
        select(Mod)
        .where(Mod.first_seen_at >= since.isoformat(), Mod.ignored.is_(False))
        .order_by(Mod.first_seen_at.desc())
        .limit(60)
    ).all()
    if not mods:
        return {"generated": False, "reason": "no_recent_mods", "items_scanned": 0, "items_matched": 0}

    total_mods = session.exec(select(func.count(Mod.id)).where(Mod.ignored.is_(False))).one()
    week_start = datetime.now(UTC) - timedelta(days=datetime.now(UTC).weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
    new_mods_this_week = session.exec(
        select(func.count(Mod.id)).where(
            Mod.first_seen_at >= week_start.isoformat(),
            Mod.ignored.is_(False),
        )
    ).one()

    context = "\n".join(
        f"- {mod.title} | game={mod.game} | downloads={mod.downloads or 0} | endorsements={mod.endorsements or 0} | summary={mod.original_summary or ''}"
        for mod in mods[:30]
    )
    report_prompt = (
        "你是 Mod 情报分析助手。根据下面近期抓取到的 Mod 列表生成一份摘要汇总报告。\n"
        f"输出语言：{output_language}。必须全篇使用该语言输出；不要因为 Mod 原文摘要是英文就改用英文。\n"
        f"侧重点：{prompt_focus}\n"
        "当前数量："
        f"已追踪 Mod 总数={total_mods}；本周新增 Mod={new_mods_this_week}；本次用于分析的近期样本={len(mods)}。\n"
        "要求：结构化输出，包含总体趋势、重点 Mod、值得继续查看的内容；不要扩展到数据无法支撑的额外章节。\n"
        "近期 Mod：\n"
        f"{context}"
    )

    report = ""
    used_provider = "none"
    used_model = "none"
    for provider_config in get_provider_chain(settings_svc):
        used_provider, api_key, base_url, used_model = resolve_provider_config(provider_config)
        if not provider_config_has_credentials(provider_config):
            continue
        client = create_client(used_provider, api_key, base_url)
        report = await client.chat(report_prompt, used_model, max_tokens=1500)
        if report:
            break

    return {
        "generated": bool(report),
        "provider": used_provider,
        "model": used_model,
        "report": report or "",
        "window_minutes": window_minutes,
        "total_mods": total_mods,
        "new_mods_this_week": new_mods_this_week,
        "items_scanned": len(mods),
        "items_matched": len(mods),
    }


def notify_summary_report_complete(
    session: Session,
    result: dict,
    *,
    notification_service_cls: type[SystemNotificationService] = SystemNotificationService,
) -> None:
    """处理当前模块的业务逻辑并返回结果。"""
    if not result.get("generated"):
        return
    notification_service_cls(session).create_event(
        event_type="llm_summary_report_complete",
        title="摘要汇总报告完成",
        message=f"已生成摘要汇总报告，样本 {int(result.get('items_matched', 0) or 0)} 个。{str(result.get('report') or '')[:160]}",
    )
