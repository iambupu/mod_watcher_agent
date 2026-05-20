import json
import os
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.settings import Setting


class SettingsService:
    DEFAULTS: dict[str, str] = {}

    @staticmethod
    def _default_llm_providers() -> list[dict]:
        return [
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
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
            },
            {
                "provider": "deepseek",
                "enabled": False,
                "priority": 3,
                "model": "deepseek-v4-flash",
                "api_key": "",
                "base_url": "https://api.deepseek.com/v1",
            },
            {
                "provider": "siliconflow",
                "enabled": False,
                "priority": 4,
                "model": "Qwen/Qwen3-8B",
                "api_key": "",
                "base_url": "https://api.siliconflow.cn/v1",
            },
            {
                "provider": "xai",
                "enabled": False,
                "priority": 5,
                "model": "grok-4.20-reasoning",
                "api_key": "",
                "base_url": "https://api.x.ai/v1",
            },
            {
                "provider": "kimi",
                "enabled": False,
                "priority": 6,
                "model": "kimi-k2.6",
                "api_key": "",
                "base_url": "https://api.moonshot.cn/v1",
            },
            {
                "provider": "qwen",
                "enabled": False,
                "priority": 7,
                "model": "qwen-plus",
                "api_key": "",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            },
            {
                "provider": "minimax",
                "enabled": False,
                "priority": 8,
                "model": "MiniMax-M2.7",
                "api_key": "",
                "base_url": "https://api.minimax.io/v1",
            },
        ]

    @classmethod
    def build_defaults(cls) -> dict[str, str]:
        return {
            "game_domain": "skyrimspecialedition",
            "nexus_api_key_configured": "false",
            "adult_policy": "include",
            "ui_language": "zh-CN",
            "summary_language": "zh-CN",
            "summary_mode": "bilingual",
            "summary_report_interval_minutes": "0",
            "summary_report_prompt": "",
            "watchdog_check_interval_minutes": "10",
            "watchdog_grace_minutes": "60",
            "watchdog_max_catchup_per_run": "3",
            "nexus_api_key": "",
            "openai_api_key": "",
            "telegram_bot_token": "",
            "telegram_chat_id": "",
            "discord_webhook_url": "",
            "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
            "llm_model": os.getenv("LLM_MODEL", ""),
            "llm_api_key": "",
            "llm_base_url": os.getenv("LLM_BASE_URL", ""),
            "llm_providers_json": json.dumps(cls._default_llm_providers(), ensure_ascii=False),
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
            "access_profile": os.getenv("MW_ACCESS_PROFILE", "local_relaxed"),
            "allow_lan": "true" if os.getenv("MW_ALLOW_LAN", "").strip().lower() in {"1", "true", "yes", "on"} else "false",
            "bind_host": os.getenv("MW_BIND_HOST", "127.0.0.1"),
        }

    def __init__(self, session: Session) -> None:
        self.session = session
        self.DEFAULTS = self.build_defaults()

    def init_defaults(self) -> None:
        for key, value in self.DEFAULTS.items():
            if self.get(key) is None:
                self.set(key, value)

    def get_all(self, exclude_prefixes: tuple[str, ...] = ()) -> dict[str, str]:
        stmt = select(Setting)
        for prefix in exclude_prefixes:
            stmt = stmt.where(Setting.key.notlike(f"{prefix}%"))
        rows = self.session.exec(stmt).all()
        return {row.key: row.value for row in rows}

    def get(self, key: str) -> str | None:
        row = self.session.exec(select(Setting).where(Setting.key == key)).first()
        return row.value if row else None

    def set(self, key: str, value: str) -> None:
        now = datetime.now(UTC).isoformat()
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
        now = datetime.now(UTC).isoformat()
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
