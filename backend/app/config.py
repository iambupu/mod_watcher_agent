import os
from dotenv import load_dotenv

load_dotenv()


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
    CORS_ORIGINS: list[str] = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS",
            "http://localhost:17501,http://127.0.0.1:17501",
        ).split(",")
        if origin.strip()
    ]
    LOCAL_ONLY_API: bool = os.getenv("LOCAL_ONLY_API", "true").lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


settings = Settings()
