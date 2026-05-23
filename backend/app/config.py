import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_list(name: str, default: str) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    return [
        item.strip()
        for item in os.getenv(name, default).split(",")
        if item.strip()
    ]


class Settings:
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL", "sqlite:///./mod_watcher.db"
    )
    NEXUS_API_KEY: str = os.getenv("NEXUS_API_KEY", "")
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")
    DISCORD_WEBHOOK_URL: str = os.getenv("DISCORD_WEBHOOK_URL", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    LLM_MODEL: str = os.getenv("LLM_MODEL", "gpt-4o-mini")
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", "")
    llm_provider: str = os.getenv("LLM_PROVIDER", "openai")
    POLL_INTERVAL_MINUTES: int = int(
        os.getenv("POLL_INTERVAL_MINUTES", "60")
    )
    DIGEST_CRON: str = os.getenv("DIGEST_CRON", "0 9 * * *")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")
    LOG_DIR: str = os.getenv("LOG_DIR", "../log")
    GAME_ALIAS_FILE: str = os.getenv("GAME_ALIAS_FILE", "game_aliases.json")
    # Local-first security settings (v0.2.0)
    _LEGACY_LOCAL_ONLY_API: bool = _env_bool("LOCAL_ONLY_API", True)
    MW_ACCESS_PROFILE: str = (
        os.getenv("MW_ACCESS_PROFILE")
        or ("local_relaxed" if _LEGACY_LOCAL_ONLY_API else "shared_lan")
    ).strip().lower()
    MW_BIND_HOST: str = (os.getenv("MW_BIND_HOST") or "127.0.0.1").strip()
    MW_ALLOW_LAN: bool = _env_bool("MW_ALLOW_LAN", not _LEGACY_LOCAL_ONLY_API)
    MW_ADMIN_TOKEN: str = (os.getenv("MW_ADMIN_TOKEN") or "").strip()
    MW_ALLOW_LOCAL_LLM: bool = _env_bool("MW_ALLOW_LOCAL_LLM", True)
    MW_ALLOWED_ORIGINS: list[str] = _env_list(
        "MW_ALLOWED_ORIGINS",
        "http://localhost:17501,http://127.0.0.1:17501",
    )
    # Legacy compatibility knobs (lower priority than MW_* keys)
    CORS_ORIGINS: list[str] = _env_list(
        "CORS_ORIGINS",
        "http://localhost:17501,http://127.0.0.1:17501",
    )
    LOCAL_ONLY_API: bool = _LEGACY_LOCAL_ONLY_API


settings = Settings()
