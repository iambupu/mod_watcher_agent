from sqlmodel import SQLModel, Session, create_engine
from sqlalchemy import text
from typing import Generator

from app.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)


def init_db() -> None:
    SQLModel.metadata.create_all(engine)
    # Lightweight runtime migration for existing SQLite databases.
    with engine.begin() as conn:
        cols = conn.execute(text("PRAGMA table_info('watch_rules')")).fetchall()
        col_names = {str(row[1]) for row in cols}
        if "interval_minutes" not in col_names:
            conn.execute(text("ALTER TABLE watch_rules ADD COLUMN interval_minutes INTEGER DEFAULT 360"))
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
