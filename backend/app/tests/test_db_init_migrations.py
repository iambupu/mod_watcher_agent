from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import create_engine

import app.models  # noqa: F401
from app import db as app_db


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_init_db_completes_lightweight_schema_before_stamping_unversioned_db(monkeypatch):
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                CREATE TABLE agent_messages (
                    id INTEGER PRIMARY KEY,
                    message_id VARCHAR(128) NOT NULL,
                    role VARCHAR(32) NOT NULL,
                    text TEXT NOT NULL,
                    session_id VARCHAR(128) NOT NULL,
                    created_at VARCHAR(64) NOT NULL,
                    sort_index INTEGER NOT NULL,
                    matches_json TEXT
                )
                """
            )
        )

    stamp_calls = []

    def fake_stamp(cfg, revision):
        stamp_calls.append(revision)

    monkeypatch.setattr(app_db, "engine", engine)

    import alembic.command as alembic_command

    monkeypatch.setattr(alembic_command, "stamp", fake_stamp)
    monkeypatch.setattr(alembic_command, "upgrade", lambda cfg, revision: None)

    app_db.init_db()

    columns = {column["name"] for column in inspect(engine).get_columns("agent_messages")}
    assert {"llm_provider", "llm_model", "response_cards_json", "audit_json"}.issubset(columns)
    index_names = {row["name"] for row in inspect(engine).get_indexes("job_runs")}
    assert "ix_job_runs_started_at_desc" in index_names
    mod_index_names = {row["name"] for row in inspect(engine).get_indexes("mods")}
    assert "ix_mods_ignored_game_domain_game" in mod_index_names
    assert "ix_mods_ignored_downloads_endorsements_first_seen_at" in mod_index_names
    assert stamp_calls == ["head"]


def test_init_db_runs_mod_identity_cleanup_once(monkeypatch):
    engine = _make_engine()

    stamp_calls = []
    dedupe_calls = 0

    def fake_stamp(cfg, revision):
        stamp_calls.append(revision)

    def fake_dedupe(conn):
        nonlocal dedupe_calls
        dedupe_calls += 1

    monkeypatch.setattr(app_db, "engine", engine)
    monkeypatch.setattr(app_db, "_dedupe_mod_rows_with_foreign_keys", fake_dedupe)

    import alembic.command as alembic_command

    monkeypatch.setattr(alembic_command, "stamp", fake_stamp)
    monkeypatch.setattr(alembic_command, "upgrade", lambda cfg, revision: None)

    app_db.init_db()

    assert stamp_calls == ["head"]
    assert dedupe_calls == 1
