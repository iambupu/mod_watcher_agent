from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from sqlmodel import Session, select

from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
from app.services.llm_client import create_llm_client
from app.services.llm_provider_config import (
    get_provider_chain,
    provider_config_has_credentials,
    resolve_provider_config,
)
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.summary_report_service import REPORT_LANGUAGE_NAMES
from app.services.system_notification_service import SystemNotificationService
from app.utils.boolean import parse_bool
from app.utils.time import parse_utc_datetime

DigestPeriod = Literal["daily", "weekly"]
DigestTextGenerator = Callable[
    [SettingsService, DigestPeriod, datetime, datetime, list[Mod], list[dict]],
    Awaitable[tuple[str, str, str]],
]

DAILY_LAST_RUN_KEY = "digest_daily_last_window_end"
WEEKLY_LAST_RUN_KEY = "digest_weekly_last_window_end"


def local_now() -> datetime:
    """处理当前模块的业务逻辑并返回结果。"""
    return datetime.now().astimezone()


def scheduled_window(period: DigestPeriod, now: datetime | None = None) -> tuple[datetime, datetime] | None:
    """处理当前模块的业务逻辑并返回结果。"""
    current = now or local_now()
    if period == "daily":
        end_local = datetime.combine(current.date(), time(hour=8), tzinfo=current.tzinfo)
        if current < end_local:
            return None
        return end_local - timedelta(hours=24), end_local

    week_start = current.date() - timedelta(days=current.weekday())
    end_local = datetime.combine(week_start, time(hour=0, minute=1), tzinfo=current.tzinfo)
    if current < end_local:
        return None
    return end_local - timedelta(days=7), end_local


def last_run_key(period: DigestPeriod) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return DAILY_LAST_RUN_KEY if period == "daily" else WEEKLY_LAST_RUN_KEY


def period_label(period: DigestPeriod, ui_language: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    if ui_language == "en-US":
        return "Daily" if period == "daily" else "Weekly"
    if ui_language == "ja-JP":
        return "日次" if period == "daily" else "週次"
    return "每日" if period == "daily" else "每周"


def should_run_digest(settings_svc: SettingsService, period: DigestPeriod, window_end: datetime, force: bool) -> bool:
    """判断流程是否需要继续执行。"""
    if force:
        return True
    last_run = parse_utc_datetime(settings_svc.get(last_run_key(period)))
    return last_run is None or last_run < window_end.astimezone(UTC)


def collect_digest_items(session: Session, window_start: datetime, window_end: datetime) -> tuple[list[Mod], list[dict]]:
    """处理当前模块的业务逻辑并返回结果。"""
    start_utc = window_start.astimezone(UTC).isoformat()
    end_utc = window_end.astimezone(UTC).isoformat()
    mods = session.exec(
        select(Mod)
        .where(
            Mod.first_seen_at >= start_utc,
            Mod.first_seen_at < end_utc,
            Mod.ignored == False,  # noqa: E712
        )
        .order_by(Mod.first_seen_at.desc())
        .limit(80)
    ).all()
    update_rows = session.exec(
        select(ModUpdateEvent, Mod)
        .join(Mod, ModUpdateEvent.mod_id == Mod.id)
        .where(
            ModUpdateEvent.detected_at >= start_utc,
            ModUpdateEvent.detected_at < end_utc,
            ModUpdateEvent.seen == False,  # noqa: E712
        )
        .order_by(ModUpdateEvent.detected_at.desc())
        .limit(80)
    ).all()
    updates = [
        {
            "mod_title": mod.title,
            "old_version": event.old_version,
            "new_version": event.new_version,
            "url": mod.url,
            "detected_at": event.detected_at,
        }
        for event, mod in update_rows
    ]
    return list(mods), updates


def build_digest_context(mods: list[Mod], updates: list[dict]) -> str:
    """构建后续流程需要的数据结构。"""
    lines = ["新发现 Mod:"]
    if mods:
        for mod in mods[:40]:
            lines.append(
                "- "
                f"{mod.title} | game={mod.game} | category={mod.category or ''} | "
                f"adult={mod.adult_content} | downloads={mod.downloads or 0} | "
                f"endorsements={mod.endorsements or 0} | likes={mod.likes or 0} | "
                f"updated={mod.updated_at_remote or ''} | summary={mod.original_summary or ''}"
            )
    else:
        lines.append("- 无")

    lines.append("")
    lines.append("收藏更新:")
    if updates:
        for item in updates[:40]:
            lines.append(
                "- "
                f"{item['mod_title']} | {item.get('old_version') or '?'} -> {item.get('new_version') or '?'} | "
                f"detected={item.get('detected_at') or ''} | url={item.get('url') or ''}"
            )
    else:
        lines.append("- 无")
    return "\n".join(lines)


async def generate_digest_text(
    settings_svc: SettingsService,
    period: DigestPeriod,
    window_start: datetime,
    window_end: datetime,
    mods: list[Mod],
    updates: list[dict],
) -> tuple[str, str, str]:
    """处理当前模块的业务逻辑并返回结果。"""
    ui_language = settings_svc.get("ui_language") or "zh-CN"
    output_language = REPORT_LANGUAGE_NAMES.get(ui_language, ui_language)
    prompt_focus = (settings_svc.get("summary_report_prompt") or "").strip()
    label = period_label(period, ui_language)
    prompt = (
        "你是 Mod 情报分析助手。请根据窗口内的新 Mod 和收藏更新生成自动汇总通知。\n"
        f"汇总类型：{label}\n"
        f"输出语言：{output_language}。必须全篇使用该语言输出。\n"
        f"时间窗口：{window_start.isoformat()} 到 {window_end.isoformat()}\n"
        f"侧重点：{prompt_focus or '关注值得尝试的 Mod、风险点、趋势和建议动作'}\n"
        "要求：结构化、简洁，包含总体概况、重点 Mod、收藏更新、风险/注意事项、建议动作。\n"
        "如果没有新内容，也要明确说明本窗口无新内容。\n"
        "窗口数据：\n"
        f"{build_digest_context(mods, updates)}"
    )
    for provider_config in get_provider_chain(settings_svc):
        used_provider, api_key, base_url, used_model = resolve_provider_config(provider_config)
        if not provider_config_has_credentials(provider_config):
            continue
        client = create_llm_client(used_provider, api_key, base_url)
        report = await client.chat(prompt, used_model, max_tokens=1800)
        if report.strip():
            return report.strip(), used_provider, used_model
    return "", "none", "none"


async def send_digest_for_window(
    session: Session,
    period: DigestPeriod,
    window_start: datetime,
    window_end: datetime,
    *,
    force: bool = False,
    generate_text: DigestTextGenerator = generate_digest_text,
) -> dict:
    """发送通知或外部请求。"""
    settings_svc = SettingsService(session)
    if not should_run_digest(settings_svc, period, window_end, force):
        return {
            "generated": False,
            "reason": "already_sent",
            "period": period,
            "items_scanned": 0,
            "items_matched": 0,
        }

    mods, updates = collect_digest_items(session, window_start, window_end)
    report, provider, model = await generate_text(settings_svc, period, window_start, window_end, mods, updates)
    if not report:
        return {
            "generated": False,
            "reason": "llm_unavailable",
            "period": period,
            "items_scanned": len(mods) + len(updates),
            "items_matched": len(mods) + len(updates),
        }

    ui_language = settings_svc.get("ui_language") or "zh-CN"
    label = period_label(period, ui_language)
    subject = f"Mod Watcher {label}摘要 ({window_end.date().isoformat()})"
    notification = NotificationService(session)
    telegram_result, discord_result = await notification.send_external_channels(report)
    desktop_event = SystemNotificationService(session).create_event(
        event_type=f"{period}_digest_complete",
        title=f"{label}摘要完成",
        message=f"新 Mod {len(mods)} 个，收藏更新 {len(updates)} 个。{report[:160]}",
    )
    desktop_enabled = (
        parse_bool(settings_svc.get("notifications_enabled"), default=True)
        and parse_bool(settings_svc.get("system_notifications_enabled"), default=True)
    )
    if desktop_enabled and desktop_event.seen:
        channel = "desktop"
        status = "sent"
        error_message = None
    elif desktop_enabled:
        channel = "desktop"
        status = "pending"
        error_message = "Windows system notification is pending or could not be dispatched"
    else:
        channel = "all"
        status, error_message = notification.combined_delivery_status([telegram_result, discord_result])
    await notification._record(
        channel,
        f"{period}_digest",
        subject,
        report,
        status,
        error_message,
    )

    settings_svc.set(last_run_key(period), window_end.astimezone(UTC).isoformat())
    return {
        "generated": True,
        "period": period,
        "provider": provider,
        "model": model,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "new_count": len(mods),
        "update_count": len(updates),
        "telegram_ok": telegram_result.ok,
        "discord_ok": discord_result.ok,
        "delivery_status": status,
        "delivery_error": error_message,
        "desktop_ok": desktop_event.seen,
        "items_scanned": len(mods) + len(updates),
        "items_matched": len(mods) + len(updates),
    }
