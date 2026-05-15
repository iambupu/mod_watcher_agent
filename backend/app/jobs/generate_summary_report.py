"""Job: Generate an LLM report for recently discovered mods."""

from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from app.db import engine
from app.jobs.tracked_jobs import run_tracked_job
from app.models.mod import Mod
from app.services.llm_client import DEFAULT_MODELS, create_llm_client
from app.services.settings_service import SettingsService


def _provider_chain(settings_svc: SettingsService) -> list[dict]:
    import json

    raw = settings_svc.get("llm_providers_json") or ""
    providers = []
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                providers = [p for p in parsed if isinstance(p, dict) and p.get("enabled")]
        except json.JSONDecodeError:
            providers = []
    if providers:
        return sorted(providers, key=lambda item: int(item.get("priority") or 999))
    return [{
        "provider": settings_svc.get("llm_provider") or "openai",
        "model": settings_svc.get("llm_model") or "",
        "api_key": settings_svc.get("llm_api_key") or "",
        "base_url": settings_svc.get("llm_base_url") or "",
        "priority": 1,
    }]


async def generate_summary_report() -> dict:
    async def handler(session: Session) -> dict:
        settings_svc = SettingsService(session)
        interval = int(settings_svc.get("summary_report_interval_minutes") or "0")
        prompt_focus = (settings_svc.get("summary_report_prompt") or "").strip()
        if interval <= 0 or not prompt_focus:
            return {"generated": False, "reason": "disabled", "items_scanned": 0, "items_matched": 0}

        since = datetime.now(timezone.utc) - timedelta(minutes=interval)
        mods = session.exec(
            select(Mod)
            .where(Mod.first_seen_at >= since.isoformat(), Mod.ignored == False)
            .order_by(Mod.first_seen_at.desc())
            .limit(60)
        ).all()
        if not mods:
            return {"generated": False, "reason": "no_recent_mods", "items_scanned": 0, "items_matched": 0}

        lines = []
        for mod in mods[:30]:
            lines.append(
                f"- {mod.title} | game={mod.game} | downloads={mod.downloads or 0} | endorsements={mod.endorsements or 0} | summary={mod.original_summary or ''}"
            )
        context = "\n".join(lines)

        report_prompt = (
            "你是 Mod 情报分析助手。根据下面近期抓取到的 Mod 列表生成一份摘要汇总报告。\n"
            f"侧重点：{prompt_focus}\n"
            "要求：结构化输出，包含总体趋势、重点 Mod、风险/注意事项、建议动作。\n"
            "近期 Mod：\n"
            f"{context}"
        )

        report = ""
        used_provider = "none"
        used_model = "none"
        for provider in _provider_chain(settings_svc):
            used_provider = str(provider.get("provider") or "openai")
            api_key = str(provider.get("api_key") or "")
            if not api_key and used_provider != "ollama":
                continue
            used_model = str(provider.get("model") or "") or DEFAULT_MODELS.get(used_provider, "gpt-4o-mini")
            client = create_llm_client(used_provider, api_key, str(provider.get("base_url") or ""))
            report = await client.chat(report_prompt, used_model, max_tokens=1500)
            if report:
                break

        return {
            "generated": bool(report),
            "provider": used_provider,
            "model": used_model,
            "report": (report[:2000] if report else ""),
            "items_scanned": len(mods),
            "items_matched": len(mods),
        }

    return await run_tracked_job("llm_summary_report", handler)
