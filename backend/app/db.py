import json
import logging
from collections.abc import Generator
from pathlib import Path

from sqlalchemy import event, inspect, text
from sqlmodel import Session, SQLModel, create_engine

from app.config import settings
from app.services.agent.retrievers.sqlite_fts_retriever import ensure_mods_fts, rebuild_mods_fts
from app.services.source_identity import canonical_external_id

logger = logging.getLogger(__name__)

engine = create_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)


if "sqlite" in settings.DATABASE_URL:

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragmas(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout = 5000")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()


def init_db() -> None:
    """处理当前模块的业务逻辑并返回结果。"""
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
                _ensure_performance_indexes()
                _normalize_mod_identity_data()
                _ensure_sqlite_fts()
                return
            command.upgrade(cfg, "head")
            _ensure_performance_indexes()
            _normalize_mod_identity_data()
            _ensure_sqlite_fts()
        else:
            # Existing databases created by SQLModel metadata may not have
            # alembic_version yet. Schema is already present after create_all(),
            # so stamp current head to avoid replaying initial CREATE TABLE ops.
            command.stamp(cfg, "head")
            _ensure_performance_indexes()
            _normalize_mod_identity_data()
            _ensure_sqlite_fts()
        return
    except BaseException:
        logger.exception("Alembic upgrade failed; falling back to manual migrations.")

    # ── Fallback: lightweight runtime migration for existing SQLite DBs ──
    _apply_lightweight_migrations()
    _ensure_performance_indexes()
    _ensure_sqlite_fts()


def _ensure_sqlite_fts() -> None:
    if engine.dialect.name != "sqlite":
        return
    with Session(engine) as session:
        if ensure_mods_fts(session):
            rebuild_mods_fts(session)


def _ensure_performance_indexes() -> None:
    if engine.dialect.name != "sqlite":
        return
    statements = [
        "CREATE INDEX IF NOT EXISTS ix_mods_ignored_first_seen_at ON mods(ignored, first_seen_at)",
        "CREATE INDEX IF NOT EXISTS ix_mods_ignored_downloads ON mods(ignored, downloads)",
        "CREATE INDEX IF NOT EXISTS ix_mods_ignored_endorsements ON mods(ignored, endorsements)",
        "CREATE INDEX IF NOT EXISTS ix_mods_ignored_updated_at_remote ON mods(ignored, updated_at_remote)",
        "CREATE INDEX IF NOT EXISTS ix_mods_game_ignored ON mods(game, ignored)",
        "CREATE INDEX IF NOT EXISTS ix_mods_game_domain_ignored ON mods(game_domain, ignored)",
        "CREATE INDEX IF NOT EXISTS ix_mods_source_ignored ON mods(source, ignored)",
        "CREATE INDEX IF NOT EXISTS ix_mods_category_ignored ON mods(category, ignored)",
        "CREATE INDEX IF NOT EXISTS ix_mod_summaries_lookup ON mod_summaries(mod_id, language, summary_type, id)",
        "CREATE INDEX IF NOT EXISTS ix_mod_summaries_language_type_mod ON mod_summaries(language, summary_type, mod_id)",
    ]
    with engine.begin() as conn:
        mod_cols = conn.execute(text("PRAGMA table_info('mods')")).fetchall()
        mod_col_names = {str(row[1]) for row in mod_cols}
        if mod_cols and "translated_title_zh" not in mod_col_names:
            conn.execute(text("ALTER TABLE mods ADD COLUMN translated_title_zh VARCHAR(512)"))
        for statement in statements:
            conn.execute(text(statement))


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
        if agent_message_cols and "audit_json" not in agent_message_col_names:
            conn.execute(text("ALTER TABLE agent_messages ADD COLUMN audit_json TEXT"))

        mod_cols = conn.execute(text("PRAGMA table_info('mods')")).fetchall()
        mod_col_names = {str(row[1]) for row in mod_cols}
        if mod_cols and "translated_title_zh" not in mod_col_names:
            conn.execute(text("ALTER TABLE mods ADD COLUMN translated_title_zh VARCHAR(512)"))

        _dedupe_mod_rows_with_foreign_keys(conn)
        conn.execute(
            text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_mod_source_external_id_idx "
                "ON mods(source, external_id)"
            )
        )


def _normalize_mod_identity_data() -> None:
    """Normalize mod identity and merge duplicates for SQLite databases."""
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as conn:
        _dedupe_mod_rows_with_foreign_keys(conn)


def _dedupe_mod_rows_with_foreign_keys(conn) -> None:
    mod_columns = _table_column_names(conn, "mods")
    if not {"id", "source", "external_id"}.issubset(mod_columns):
        return
    _bulk_rewrite_nexusmods_numeric_ids(conn, mod_columns)

    select_columns = ["id", "source", "external_id"]
    for optional_name in ("url", "game", "game_domain", "last_seen_at"):
        if optional_name in mod_columns:
            select_columns.append(optional_name)

    # Keep Python-level canonicalization on non-Nexus sources (and unresolved Nexus IDs),
    # while the Nexus bulk rewrite above handles the large hot path.
    candidate_rows = conn.execute(
        text(
            f"""
            SELECT {', '.join(select_columns)}
            FROM mods
            WHERE source != 'nexusmods'
               OR external_id NOT LIKE '%:%'
            """
        )
    ).mappings().all()

    for row in candidate_rows:
        source = str(row["source"] or "").strip().lower()
        external_id = str(row["external_id"] or "").strip()
        if not source or not external_id:
            continue
        url = str(row.get("url") or "").strip()
        canonical = canonical_external_id(
            source,
            external_id,
            url,
            game=str(row.get("game") or ""),
            game_domain=str(row.get("game_domain") or ""),
        )
        if source == "nexusmods" and ":" not in canonical and external_id.isdigit():
            domain = str(row.get("game_domain") or "").strip().lower()
            if domain:
                canonical = f"{domain}:{external_id}"
        canonical = canonical.strip()
        if canonical and canonical != external_id:
            existing = conn.execute(
                text(
                    """
                    SELECT id
                    FROM mods
                    WHERE source = :source
                      AND external_id = :external_id
                    LIMIT 1
                    """
                ),
                {"source": source, "external_id": canonical},
            ).mappings().first()
            if existing is not None and int(existing["id"]) != int(row["id"]):
                _merge_mod_references(conn, int(existing["id"]), int(row["id"]))
                conn.execute(text("DELETE FROM mods WHERE id = :mod_id"), {"mod_id": int(row["id"])})
                continue
            conn.execute(
                text("UPDATE mods SET external_id = :external_id WHERE id = :mod_id"),
                {"external_id": canonical, "mod_id": int(row["id"])},
            )

    if "game_domain" in mod_columns:
        conn.execute(
            text(
                """
                UPDATE mods
                SET game_domain = LOWER(SUBSTR(external_id, 1, INSTR(external_id, ':') - 1))
                WHERE source = 'nexusmods'
                  AND INSTR(external_id, ':') > 1
                  AND (game_domain IS NULL OR TRIM(game_domain) = '')
                """
            )
        )

    _cleanup_exact_mod_duplicates(conn)


def _bulk_rewrite_nexusmods_numeric_ids(conn, mod_columns: set[str]) -> None:
    if "url" not in mod_columns:
        if "game_domain" in mod_columns:
            conn.execute(
                text(
                    """
                    UPDATE mods
                    SET external_id = LOWER(TRIM(game_domain)) || ':' || TRIM(external_id)
                    WHERE source = 'nexusmods'
                      AND TRIM(external_id) GLOB '[0-9]*'
                      AND TRIM(external_id) NOT LIKE '%:%'
                      AND game_domain IS NOT NULL
                      AND TRIM(game_domain) != ''
                    """
                )
            )
        return

    conn.execute(
        text(
            """
            UPDATE OR IGNORE mods
            SET external_id = (
                CASE
                    WHEN game_domain IS NOT NULL AND TRIM(game_domain) != ''
                        THEN LOWER(TRIM(game_domain)) || ':' || TRIM(external_id)
                    WHEN url IS NOT NULL
                        AND INSTR(LOWER(url), 'nexusmods.com/') > 0
                        AND INSTR(
                            SUBSTR(
                                LOWER(url),
                                INSTR(LOWER(url), 'nexusmods.com/') + LENGTH('nexusmods.com/')
                            ),
                            '/mods/'
                        ) > 1
                        THEN
                            SUBSTR(
                                SUBSTR(
                                    LOWER(url),
                                    INSTR(LOWER(url), 'nexusmods.com/') + LENGTH('nexusmods.com/')
                                ),
                                1,
                                INSTR(
                                    SUBSTR(
                                        LOWER(url),
                                        INSTR(LOWER(url), 'nexusmods.com/') + LENGTH('nexusmods.com/')
                                    ),
                                    '/mods/'
                                ) - 1
                            ) || ':' || TRIM(external_id)
                    ELSE TRIM(external_id)
                END
            )
            WHERE source = 'nexusmods'
              AND TRIM(external_id) GLOB '[0-9]*'
              AND TRIM(external_id) NOT LIKE '%:%'
            """
        )
    )


def _cleanup_exact_mod_duplicates(conn) -> None:
    duplicates = conn.execute(
        text(
            """
            SELECT source, external_id
            FROM mods
            GROUP BY source, external_id
            HAVING COUNT(*) > 1
            """
        )
    ).mappings().all()
    for duplicate in duplicates:
        rows = conn.execute(
            text(
                """
                SELECT id
                FROM mods
                WHERE source = :source AND external_id = :external_id
                ORDER BY id DESC
                """
            ),
            {"source": duplicate["source"], "external_id": duplicate["external_id"]},
        ).mappings().all()
        if not rows:
            continue
        keeper_id = int(rows[0]["id"])
        for row in rows[1:]:
            duplicate_id = int(row["id"])
            _merge_mod_references(conn, keeper_id, duplicate_id)
            conn.execute(text("DELETE FROM mods WHERE id = :mod_id"), {"mod_id": duplicate_id})


def _merge_mod_references(conn, keeper_mod_id: int, duplicate_mod_id: int) -> None:
    _merge_favorites_for_mod(conn, keeper_mod_id, duplicate_mod_id)
    if _table_exists(conn, "mod_summaries") and _table_has_columns(conn, "mod_summaries", {"mod_id"}):
        conn.execute(
            text("UPDATE mod_summaries SET mod_id = :keeper WHERE mod_id = :duplicate"),
            {"keeper": keeper_mod_id, "duplicate": duplicate_mod_id},
        )
    if _table_exists(conn, "mod_update_events") and _table_has_columns(conn, "mod_update_events", {"mod_id"}):
        conn.execute(
            text("UPDATE mod_update_events SET mod_id = :keeper WHERE mod_id = :duplicate"),
            {"keeper": keeper_mod_id, "duplicate": duplicate_mod_id},
        )


def _merge_favorites_for_mod(conn, keeper_mod_id: int, duplicate_mod_id: int) -> None:
    if not _table_exists(conn, "favorites") or not _table_has_columns(conn, "favorites", {"id", "mod_id"}):
        return
    keeper_favorite = conn.execute(
        text("SELECT * FROM favorites WHERE mod_id = :mod_id LIMIT 1"),
        {"mod_id": keeper_mod_id},
    ).mappings().first()
    duplicate_favorite = conn.execute(
        text("SELECT * FROM favorites WHERE mod_id = :mod_id LIMIT 1"),
        {"mod_id": duplicate_mod_id},
    ).mappings().first()
    if duplicate_favorite is None:
        return
    if keeper_favorite is None:
        conn.execute(
            text("UPDATE favorites SET mod_id = :keeper_mod_id WHERE id = :favorite_id"),
            {"keeper_mod_id": keeper_mod_id, "favorite_id": duplicate_favorite["id"]},
        )
        return

    merged_values = _merge_favorite_values(dict(keeper_favorite), dict(duplicate_favorite))
    if merged_values:
        assignments = ", ".join(f"{column} = :{column}" for column in merged_values)
        params = {"favorite_id": keeper_favorite["id"]}
        params.update(merged_values)
        conn.execute(
            text(f"UPDATE favorites SET {assignments} WHERE id = :favorite_id"),
            params,
        )

    if _table_exists(conn, "mod_update_events") and _table_has_columns(conn, "mod_update_events", {"favorite_id"}):
        conn.execute(
            text("UPDATE mod_update_events SET favorite_id = :keeper WHERE favorite_id = :duplicate"),
            {"keeper": keeper_favorite["id"], "duplicate": duplicate_favorite["id"]},
        )
    conn.execute(text("DELETE FROM favorites WHERE id = :favorite_id"), {"favorite_id": duplicate_favorite["id"]})


def _merge_favorite_values(keeper: dict, duplicate: dict) -> dict[str, object]:
    merged: dict[str, object] = {}
    if "tracking_enabled" in keeper and "tracking_enabled" in duplicate:
        merged["tracking_enabled"] = bool(keeper["tracking_enabled"]) or bool(duplicate["tracking_enabled"])
    if "notify_on_update" in keeper and "notify_on_update" in duplicate:
        merged["notify_on_update"] = bool(keeper["notify_on_update"]) or bool(duplicate["notify_on_update"])

    if _is_blank(keeper.get("user_note")) and not _is_blank(duplicate.get("user_note")):
        merged["user_note"] = duplicate.get("user_note")

    if "user_tags_json" in keeper and "user_tags_json" in duplicate:
        merged_tags = _merge_json_array_strings(keeper.get("user_tags_json"), duplicate.get("user_tags_json"))
        if merged_tags is not None:
            merged["user_tags_json"] = merged_tags

    for field_name in ("last_known_version",):
        if field_name in keeper and _is_blank(keeper.get(field_name)) and not _is_blank(duplicate.get(field_name)):
            merged[field_name] = duplicate.get(field_name)
    for field_name in ("last_known_updated_at", "last_checked_at", "updated_at"):
        if field_name in keeper and field_name in duplicate:
            merged[field_name] = _pick_max_text(keeper.get(field_name), duplicate.get(field_name))
    if "created_at" in keeper and "created_at" in duplicate:
        merged["created_at"] = _pick_min_text(keeper.get("created_at"), duplicate.get("created_at"))

    return merged


def _merge_json_array_strings(first: object, second: object) -> str | None:
    merged: list[str] = []
    for value in (first, second):
        if not isinstance(value, str) or not value.strip():
            continue
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = []
        if isinstance(parsed, list):
            for item in parsed:
                text_value = str(item).strip()
                if text_value:
                    merged.append(text_value)
    if not merged:
        return None
    return json.dumps(list(dict.fromkeys(merged)), ensure_ascii=False)


def _pick_mod_keeper(group: list[dict[str, str | int | None]]) -> dict[str, str | int | None]:
    return sorted(
        group,
        key=lambda row: (
            1 if str(row["external_id"]) == str(row["canonical_external_id"]) else 0,
            1 if str(row.get("game_domain") or "").strip() else 0,
            str(row.get("last_seen_at") or ""),
            int(row["id"]),
        ),
    )[-1]


def _is_blank(value: object) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _pick_max_text(first: object, second: object) -> str | None:
    first_text = str(first or "").strip()
    second_text = str(second or "").strip()
    if not first_text:
        return second_text or None
    if not second_text:
        return first_text
    return max(first_text, second_text)


def _pick_min_text(first: object, second: object) -> str | None:
    first_text = str(first or "").strip()
    second_text = str(second or "").strip()
    if not first_text:
        return second_text or None
    if not second_text:
        return first_text
    return min(first_text, second_text)


def _table_column_names(conn, table_name: str) -> set[str]:
    rows = conn.execute(text(f"PRAGMA table_info('{table_name}')")).fetchall()
    return {str(row[1]) for row in rows}


def _table_has_columns(conn, table_name: str, columns: set[str]) -> bool:
    return columns.issubset(_table_column_names(conn, table_name))


def _table_exists(conn, table_name: str) -> bool:
    row = conn.execute(
        text(
            """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = :table_name
            LIMIT 1
            """
        ),
        {"table_name": table_name},
    ).first()
    return row is not None


def get_session() -> Generator[Session, None, None]:
    """读取并返回对应的数据。"""
    with Session(engine) as session:
        yield session
