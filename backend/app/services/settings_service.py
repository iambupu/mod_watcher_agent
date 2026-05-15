import os
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.models.settings import Setting


DEFAULT_LLM_PROVIDERS = [
    {
        "provider": "ollama",
        "enabled": True,
        "priority": 1,
        "model": os.getenv("LLM_MODEL", "") or "qwen3:8b",
        "api_key": "",
        "base_url": os.getenv("LLM_BASE_URL", "") or "http://localhost:11434/v1",
    },
    {
        "provider": "openai",
        "enabled": False,
        "priority": 2,
        "model": "gpt-4o-mini",
        "api_key": os.getenv("OPENAI_API_KEY", ""),
        "base_url": "https://api.openai.com/v1",
    },
    {
        "provider": "deepseek",
        "enabled": False,
        "priority": 3,
        "model": "deepseek-chat",
        "api_key": "",
        "base_url": "https://api.deepseek.com/v1",
    },
]


class SettingsService:
    DEFAULTS = {
        "game_domain": "skyrimspecialedition",
        "nexus_api_key_configured": "false",
        "adult_policy": "include",
        "ui_language": "zh-CN",
        "summary_language": "zh-CN",
        "summary_mode": "bilingual",
        "summary_report_interval_minutes": "0",
        "summary_report_prompt": "",
        "nexus_api_key": os.getenv("NEXUS_API_KEY", ""),
        "openai_api_key": os.getenv("OPENAI_API_KEY", ""),
        "telegram_bot_token": os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "discord_webhook_url": os.getenv("DISCORD_WEBHOOK_URL", ""),
        "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
        "llm_model": os.getenv("LLM_MODEL", ""),
        "llm_api_key": os.getenv("LLM_API_KEY", "") or os.getenv("OPENAI_API_KEY", ""),
        "llm_base_url": os.getenv("LLM_BASE_URL", ""),
        "llm_providers_json": json.dumps(DEFAULT_LLM_PROVIDERS, ensure_ascii=False),
        "auto_start": "false",
        "notifications_enabled": "true",
        "system_notifications_enabled": "true",
        "database_path": "mod_watcher.db",
        "proxy_enabled": "false",
        "proxy_type": "http",
        "proxy_host": "",
        "proxy_port": "",
        "proxy_username": "",
        "proxy_password": "",
    }

    def __init__(self, session: Session) -> None:
        self.session = session

    def init_defaults(self) -> None:
        for key, value in self.DEFAULTS.items():
            if self.get(key) is None:
                self.set(key, value)
            elif key == "summary_language" and self.get(key) == "en":
                self.set(key, value)

    def get_all(self) -> dict[str, str]:
        rows = self.session.exec(select(Setting)).all()
        return {row.key: row.value for row in rows}

    def get(self, key: str) -> str | None:
        row = self.session.exec(select(Setting).where(Setting.key == key)).first()
        return row.value if row else None

    def set(self, key: str, value: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing = self.session.exec(
            select(Setting).where(Setting.key == key)
        ).first()
        if existing:
            existing.value = value
            existing.updated_at = now
        else:
            setting = Setting(key=key, value=value, updated_at=now)
            self.session.add(setting)
        self.session.commit()

    def set_batch(self, items: dict[str, str]) -> None:
        now = datetime.now(timezone.utc).isoformat()
        existing_rows = self.session.exec(
            select(Setting).where(Setting.key.in_(list(items.keys())))
        ).all()
        existing_by_key = {row.key: row for row in existing_rows}
        for key, value in items.items():
            existing = existing_by_key.get(key)
            if existing:
                existing.value = value
                existing.updated_at = now
            else:
                self.session.add(Setting(key=key, value=value, updated_at=now))
        self.session.commit()
