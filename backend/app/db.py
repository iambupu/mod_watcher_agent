import logging
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)

    # ── Alembic managed migrations ──────────────────────────────────
    alembic_ini = Path(__file__).resolve().parents[1] / "alembic.ini"
    try:
        from alembic.config import Config as AlembicConfig

        from alembic import command

        cfg = AlembicConfig(str(alembic_ini))
        inspector = inspect(engine)
        has_alembic_version = inspector.has_table("alembic_version")
        if has_alembic_version:
            with engine.connect() as conn:
                version_rows = conn.execute(text("SELECT version_num FROM alembic_version")).fetchall()
            if not version_rows:
                command.stamp(cfg, "head")
                return
            command.upgrade(cfg, "head")
        else:
            # Existing databases created by SQLModel metadata may not have
            # alembic_version yet. Schema is already present after create_all(),
            # so stamp current head to avoid replaying initial CREATE TABLE ops.
            command.stamp(cfg, "head")
        return
    except BaseException:
        logger.exception("Alembic upgrade failed; falling back to manual migrations.")

    # ── Fallback: lightweight runtime migration for existing SQLite DBs ──
    _apply_lightweight_migrations()


def _apply_lightweight_migrations() -> None:
    """Keep older local SQLite databases compatible with the current models."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info('watch_rules')")).fetchall()
        col_names = {str(row[1]) for row in cols}
        if "interval_minutes" not in col_names:
            conn.execute(text("ALTER TABLE watch_rules ADD COLUMN interval_minutes INTEGER DEFAULT 360"))

        notification_cols = conn.execute(text("PRAGMA table_info('notifications')")).fetchall()
        notification_col_names = {str(row[1]) for row in notification_cols}
        if notification_cols and "read" not in notification_col_names:
            conn.execute(text("ALTER TABLE notifications ADD COLUMN read BOOLEAN DEFAULT 0 NOT NULL"))

        agent_message_cols = conn.execute(text("PRAGMA table_info('agent_messages')")).fetchall()
        agent_message_col_names = {str(row[1]) for row in agent_message_cols}
        if agent_message_cols and "llm_provider" not in agent_message_col_names:
            conn.execute(text("ALTER TABLE agent_messages ADD COLUMN llm_provider VARCHAR(64)"))
        if agent_message_cols and "llm_model" not in agent_message_col_names:
            conn.execute(text("ALTER TABLE agent_messages ADD COLUMN llm_model VARCHAR(128)"))
        if agent_message_cols and "response_cards_json" not in agent_message_col_names:
            conn.execute(text("ALTER TABLE agent_messages ADD COLUMN response_cards_json TEXT"))

        # Deduplicate legacy rows before adding the unique index.
        conn.execute(
            text(
                """
                DELETE FROM mods
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM mods
                    GROUP BY source, external_id
                )
                """
            )
        )
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_mod_source_external_id_idx "
                "ON mods(source, external_id)"
            )
        )


def get_session() -> Generator[Session, None, None]:
    with Session(engine) as session:
        yield session
