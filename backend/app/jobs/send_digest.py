"""Jobs: generate and send daily/weekly LLM digest notifications."""

import logging
from datetime import UTC, datetime, time, timedelta
from typing import Literal

from sqlmodel import Session, select

from app.db import engine
from app.jobs.generate_summary_report import REPORT_LANGUAGE_NAMES, _provider_chain
from app.jobs.tracked_jobs import run_tracked_job
from app.models.mod import Mod
from app.models.update_event import ModUpdateEvent
from app.services.llm_client import DEFAULT_MODELS, create_llm_client
from app.services.notification_service import NotificationService
from app.services.settings_service import SettingsService
from app.services.system_notification_service import SystemNotificationService

logger = logging.getLogger(__name__)

DigestPeriod = Literal["daily", "weekly"]

_DAILY_LAST_RUN_KEY = "digest_daily_last_window_end"
_WEEKLY_LAST_RUN_KEY = "digest_weekly_last_window_end"


def _local_now() -> datetime:
    return datetime.now().astimezone()


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _scheduled_window(period: DigestPeriod, now: datetime | None = None) -> tuple[datetime, datetime] | None:
    local_now = now or _local_now()
    if period == "daily":
        end_local = datetime.combine(local_now.date(), time(hour=8), tzinfo=local_now.tzinfo)
        if local_now < end_local:
            return None
        return end_local - timedelta(hours=24), end_local

    week_start = local_now.date() - timedelta(days=local_now.weekday())
    end_local = datetime.combine(week_start, time(hour=0, minute=1), tzinfo=local_now.tzinfo)
    if local_now < end_local:
        return None
    return end_local - timedelta(days=7), end_local


def _last_run_key(period: DigestPeriod) -> str:
    return _DAILY_LAST_RUN_KEY if period == "daily" else _WEEKLY_LAST_RUN_KEY


def _period_label(period: DigestPeriod, ui_language: str) -> str:
    if ui_language == "en-US":
        return "Daily" if period == "daily" else "Weekly"
    if ui_language == "ja-JP":
        return "日次" if period == "daily" else "週次"
    return "每日" if period == "daily" else "每周"


def _should_run_digest(settings_svc: SettingsService, period: DigestPeriod, window_end: datetime, force: bool) -> bool:
    if force:
        return True
    last_run = _parse_iso(settings_svc.get(_last_run_key(period)))
    return last_run is None or last_run < window_end.astimezone(UTC)


def _collect_digest_items(session: Session, window_start: datetime, window_end: datetime) -> tuple[list[Mod], list[dict]]:
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


def _build_digest_context(mods: list[Mod], updates: list[dict]) -> str:
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


async def _generate_digest_text(
    settings_svc: SettingsService,
    period: DigestPeriod,
    window_start: datetime,
    window_end: datetime,
    mods: list[Mod],
    updates: list[dict],
) -> tuple[str, str, str]:
    ui_language = settings_svc.get("ui_language") or "zh-CN"
    output_language = REPORT_LANGUAGE_NAMES.get(ui_language, ui_language)
    prompt_focus = (settings_svc.get("summary_report_prompt") or "").strip()
    label = _period_label(period, ui_language)
    context = _build_digest_context(mods, updates)
    prompt = (
        "你是 Mod 情报分析助手。请根据窗口内的新 Mod 和收藏更新生成自动汇总通知。\n"
        f"汇总类型：{label}\n"
        f"输出语言：{output_language}。必须全篇使用该语言输出。\n"
        f"时间窗口：{window_start.isoformat()} 到 {window_end.isoformat()}\n"
        f"侧重点：{prompt_focus or '关注值得尝试的 Mod、风险点、趋势和建议动作'}\n"
        "要求：结构化、简洁，包含总体概况、重点 Mod、收藏更新、风险/注意事项、建议动作。\n"
        "如果没有新内容，也要明确说明本窗口无新内容。\n"
        "窗口数据：\n"
        f"{context}"
    )
    for provider in _provider_chain(settings_svc):
        used_provider = str(provider.get("provider") or "openai")
        api_key = str(provider.get("api_key") or "")
        if not api_key and used_provider != "ollama":
            continue
        used_model = str(provider.get("model") or "") or DEFAULT_MODELS.get(used_provider, "gpt-4o-mini")
        client = create_llm_client(used_provider, api_key, str(provider.get("base_url") or ""))
        report = await client.chat(prompt, used_model, max_tokens=1800)
        if report.strip():
            return report.strip(), used_provider, used_model
    return "", "none", "none"


async def _send_digest_for_window(
    session: Session,
    period: DigestPeriod,
    window_start: datetime,
    window_end: datetime,
    *,
    force: bool = False,
) -> dict:
    settings_svc = SettingsService(session)
    if not _should_run_digest(settings_svc, period, window_end, force):
        return {
            "generated": False,
            "reason": "already_sent",
            "period": period,
            "items_scanned": 0,
            "items_matched": 0,
        }

    mods, updates = _collect_digest_items(session, window_start, window_end)
    report, provider, model = await _generate_digest_text(settings_svc, period, window_start, window_end, mods, updates)
    if not report:
        return {
            "generated": False,
            "reason": "llm_unavailable",
            "period": period,
            "items_scanned": len(mods) + len(updates),
            "items_matched": len(mods) + len(updates),
        }

    ui_language = settings_svc.get("ui_language") or "zh-CN"
    label = _period_label(period, ui_language)
    subject = f"Mod Watcher {label}摘要 ({window_end.date().isoformat()})"
    notification = NotificationService(session)
    telegram_ok = await notification.send_telegram_message(report)
    discord_ok = await notification.send_discord_webhook(report)
    await notification._record(
        "all",
        f"{period}_digest",
        subject,
        report,
        "sent" if telegram_ok or discord_ok else "failed",
    )

    settings_svc.set(_last_run_key(period), window_end.astimezone(UTC).isoformat())
    SystemNotificationService(session).create_event(
        event_type=f"{period}_digest_complete",
        title=f"{label}摘要完成",
        message=f"新 Mod {len(mods)} 个，收藏更新 {len(updates)} 个。{report[:160]}",
    )
    return {
        "generated": True,
        "period": period,
        "provider": provider,
        "model": model,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "new_count": len(mods),
        "update_count": len(updates),
        "telegram_ok": telegram_ok,
        "discord_ok": discord_ok,
        "items_scanned": len(mods) + len(updates),
        "items_matched": len(mods) + len(updates),
    }


async def send_digest(period: DigestPeriod = "daily", *, force: bool = False) -> dict:
    window = _scheduled_window(period)
    if window is None:
        return {"generated": False, "reason": "not_due", "period": period, "items_scanned": 0, "items_matched": 0}
    with Session(engine) as session:
        return await _send_digest_for_window(session, period, window[0], window[1], force=force)


async def send_daily_digest() -> dict:
    return await send_digest("daily")


async def send_weekly_digest() -> dict:
    return await send_digest("weekly")


async def _run_digest_catchup_impl(session: Session, trigger: str) -> dict:
    results: list[dict] = []
    for period in ("daily", "weekly"):
        window = _scheduled_window(period)
        if window is None:
            continue
        result = await _send_digest_for_window(session, period, window[0], window[1])
        if result.get("generated") or result.get("reason") != "already_sent":
            results.append(result)
    return {
        "checked": True,
        "trigger": trigger,
        "results": results,
        "items_scanned": sum(int(item.get("items_scanned", 0) or 0) for item in results),
        "items_matched": sum(int(item.get("items_matched", 0) or 0) for item in results),
    }


async def run_digest_catchup(trigger: str = "scheduled") -> dict:
    async def handler(session: Session) -> dict:
        return await _run_digest_catchup_impl(session, trigger)

    return await run_tracked_job(
        "digest_catchup",
        handler,
        metadata={"trigger": trigger},
    )
