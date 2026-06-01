import json
import os
from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.settings import Setting
from app.services.llm_provider_config import default_provider_configs
from app.utils.boolean import parse_bool


class SettingsService:
    @staticmethod
    def _default_llm_providers() -> list[dict]:
        """内部辅助函数，用于拆分上层流程中的局部规则。"""
        return default_provider_configs()

    @classmethod
    def build_defaults(cls) -> dict[str, str]:
        """构建后续流程需要的数据结构。"""
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
            "google_search_api_key": "",
            "google_search_engine_id": "",
            "loverslab_search_scrape_enabled": "true",
            "loverslab_search_scrape_engine": "duckduckgo",
            "openai_api_key": "",
            "telegram_bot_token": "",
            "telegram_chat_id": "",
            "discord_webhook_url": "",
            "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
            "llm_model": os.getenv("LLM_MODEL", ""),
            "llm_api_key": os.getenv("LLM_API_KEY", ""),
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
            "allow_lan": "true" if parse_bool(os.getenv("MW_ALLOW_LAN")) else "false",
            "bind_host": os.getenv("MW_BIND_HOST", "127.0.0.1"),
        }

    def __init__(self, session: Session) -> None:
        """初始化实例并保存运行所需的依赖。"""
        self.session = session
        self.DEFAULTS: dict[str, str] = self.build_defaults()

    def init_defaults(self) -> None:
        """处理当前模块的业务逻辑并返回结果。"""
        for key, value in self.DEFAULTS.items():
            if self.get(key) is None:
                self.set(key, value)

    def get_all(self, exclude_prefixes: tuple[str, ...] = ()) -> dict[str, str]:
        """读取并返回对应的数据。"""
        stmt = select(Setting)
        for prefix in exclude_prefixes:
            stmt = stmt.where(Setting.key.notlike(f"{prefix}%"))
        rows = self.session.exec(stmt).all()
        return {row.key: row.value for row in rows}

    def get(self, key: str) -> str | None:
        """读取并返回对应的数据。"""
        row = self.session.exec(select(Setting).where(Setting.key == key)).first()
        return row.value if row else None

    def set(self, key: str, value: str) -> None:
        """处理当前模块的业务逻辑并返回结果。"""
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
        """处理当前模块的业务逻辑并返回结果。"""
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
