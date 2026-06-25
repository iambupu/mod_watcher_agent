# 中文注释：封装 Agent 检索器的SQLite FTS 检索逻辑。

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session

from app.models.mod import Mod
from app.services.agent.filter_value_utils import (
    optional_min_metric,
    optional_time_window,
    url_without_query,
)
from app.services.source_identity import external_id_aliases
from app.utils.numeric import bounded_int

FTS_INDEX_VERSION = "mods_fts_v2_trigram_meta"
FTS_TABLES = ("mods_fts", "mods_fts_trigram")
FTS_META_TABLE = "mods_fts_meta"
DEFAULT_FTS_REPAIR_LIMIT = 1000


@dataclass(frozen=True)
class SqliteFtsResult:
    mod: Mod
    score: int
    stage: str = "sqlite_fts"


def ensure_mods_fts(session: Session) -> bool:
    if session.get_bind().dialect.name != "sqlite":
        return False
    try:
        _drop_legacy_mods_fts_if_needed(session)
        session.exec(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS mods_fts
                USING fts5(
                    mod_id UNINDEXED,
                    title,
                    translated_title_zh,
                    external_id,
                    author,
                    category,
                    game,
                    game_domain,
                    url,
                    tags_json,
                    original_summary,
                    translated_summary,
                    tokenize = 'unicode61'
                )
                """
            )
        )
        session.exec(
            text(
                """
                CREATE VIRTUAL TABLE IF NOT EXISTS mods_fts_trigram
                USING fts5(
                    mod_id UNINDEXED,
                    title,
                    translated_title_zh,
                    external_id,
                    author,
                    category,
                    game,
                    game_domain,
                    url,
                    tags_json,
                    original_summary,
                    translated_summary,
                    tokenize = 'trigram'
                )
                """
            )
        )
        session.exec(
            text(
                """
                CREATE TABLE IF NOT EXISTS mods_fts_meta (
                    mod_id INTEGER PRIMARY KEY,
                    index_version TEXT NOT NULL,
                    source_updated_at TEXT NOT NULL,
                    latest_summary_id INTEGER,
                    latest_summary_generated_at TEXT,
                    content_hash TEXT NOT NULL,
                    indexed_at TEXT NOT NULL
                )
                """
            )
        )
        session.exec(
            text(
                """
                CREATE INDEX IF NOT EXISTS ix_mods_fts_meta_version_indexed_at
                ON mods_fts_meta(index_version, indexed_at)
                """
            )
        )
        _drop_mods_fts_triggers(session)
        _ensure_mods_fts_triggers(session)
        session.commit()
    except OperationalError:
        session.rollback()
        return False
    return True


def rebuild_mods_fts(session: Session) -> bool:
    if not ensure_mods_fts(session):
        return False
    for table_name in FTS_TABLES:
        session.exec(text(f"DELETE FROM {table_name}"))
    session.exec(text(f"DELETE FROM {FTS_META_TABLE}"))
    for table_name in FTS_TABLES:
        session.exec(text(_insert_all_mods_fts_sql(session, table_name)))
    _populate_mods_fts_meta(session)
    session.commit()
    return True


def mods_fts_needs_rebuild(session: Session) -> bool:
    if session.get_bind().dialect.name != "sqlite":
        return False
    if not _has_mods_fts_schema(session):
        return True
    try:
        return bool(_stale_mods_fts_ids(session, limit=1))
    except OperationalError:
        session.rollback()
        return True


def _drop_legacy_mods_fts_if_needed(session: Session) -> None:
    required_columns = {
        "mod_id",
        "title",
        "translated_title_zh",
        "external_id",
        "author",
        "category",
        "game",
        "game_domain",
        "url",
        "tags_json",
        "original_summary",
        "translated_summary",
    }
    for table_name in FTS_TABLES:
        if not _has_fts_table(session, table_name):
            continue
        columns = session.exec(text(f"PRAGMA table_info('{table_name}')")).all()
        column_names = {str(row[1]) for row in columns}
        if required_columns.issubset(column_names):
            continue
        _drop_mods_fts_triggers(session)
        session.exec(text(f"DROP TABLE IF EXISTS {table_name}"))
        session.exec(text(f"DROP TABLE IF EXISTS {FTS_META_TABLE}"))


def refresh_mods_fts_row(session: Session, mod_id: int) -> None:
    if session.get_bind().dialect.name != "sqlite":
        return
    if not ensure_mods_fts(session):
        return
    _refresh_mods_fts_row(session, mod_id)


def repair_stale_mods_fts(session: Session, *, limit: int = DEFAULT_FTS_REPAIR_LIMIT) -> int:
    if session.get_bind().dialect.name != "sqlite":
        return 0
    if not ensure_mods_fts(session):
        return 0
    normalized_limit = bounded_int(
        limit,
        default=DEFAULT_FTS_REPAIR_LIMIT,
        minimum=1,
        maximum=10000,
        default_when_below_minimum=True,
    )
    stale_ids = _stale_mods_fts_ids(session, limit=normalized_limit)
    for mod_id in stale_ids:
        _refresh_mods_fts_row(session, mod_id)
    session.commit()
    return len(stale_ids)


def _refresh_mods_fts_row(session: Session, mod_id: int) -> None:
    for table_name in FTS_TABLES:
        session.execute(text(f"DELETE FROM {table_name} WHERE mod_id = :mod_id"), {"mod_id": mod_id})
        session.execute(text(_insert_single_mods_fts_sql(session, table_name)), {"mod_id": mod_id})
    _upsert_mods_fts_meta(session, mod_id)


def _insert_all_mods_fts_sql(session: Session, table_name: str) -> str:
    _assert_fts_table_name(table_name)
    translated_title_expr = (
        "COALESCE(m.translated_title_zh, '')"
        if _mods_has_column(session, "translated_title_zh")
        else "''"
    )
    return _insert_mods_fts_sql(table_name, translated_title_expr, "m.id IS NOT NULL")


def _insert_single_mods_fts_sql(session: Session, table_name: str) -> str:
    _assert_fts_table_name(table_name)
    translated_title_expr = (
        "COALESCE(m.translated_title_zh, '')"
        if _mods_has_column(session, "translated_title_zh")
        else "''"
    )
    return _insert_mods_fts_sql(table_name, translated_title_expr, "m.id = :mod_id")


def _insert_mods_fts_sql(table_name: str, translated_title_expr: str, where_clause: str) -> str:
    return f"""
        INSERT INTO {table_name}(
            rowid,
            mod_id,
            title,
            translated_title_zh,
            external_id,
            author,
            category,
            game,
            game_domain,
            url,
            tags_json,
            original_summary,
            translated_summary
        )
        SELECT
            m.id,
            m.id,
            COALESCE(m.title, ''),
            {translated_title_expr},
            COALESCE(m.external_id, ''),
            COALESCE(m.author, ''),
            COALESCE(m.category, ''),
            COALESCE(m.game, ''),
            COALESCE(m.game_domain, ''),
            COALESCE(m.url, ''),
            COALESCE(m.tags_json, ''),
            COALESCE(m.original_summary, ''),
            COALESCE(group_concat(s.content, ' '), '')
        FROM mods m
        LEFT JOIN mod_summaries s ON s.mod_id = m.id
        WHERE {where_clause}
        GROUP BY m.id
        """


def _assert_fts_table_name(table_name: str) -> None:
    if table_name not in FTS_TABLES:
        raise ValueError(f"Unsupported FTS table: {table_name}")


def _populate_mods_fts_meta(session: Session) -> None:
    batch: list[dict[str, Any]] = []
    for row in _fts_source_rows(session):
        batch.append(_fts_meta_params(row))
        if len(batch) >= 500:
            session.execute(text(_UPSERT_FTS_META_SQL), batch)
            batch.clear()
    if batch:
        session.execute(text(_UPSERT_FTS_META_SQL), batch)


def _upsert_mods_fts_meta(session: Session, mod_id: int) -> None:
    row = _fts_source_row(session, mod_id)
    if row is None:
        session.execute(text(f"DELETE FROM {FTS_META_TABLE} WHERE mod_id = :mod_id"), {"mod_id": mod_id})
        return
    session.execute(text(_UPSERT_FTS_META_SQL), _fts_meta_params(row))


_UPSERT_FTS_META_SQL = f"""
    INSERT OR REPLACE INTO {FTS_META_TABLE}(
        mod_id,
        index_version,
        source_updated_at,
        latest_summary_id,
        latest_summary_generated_at,
        content_hash,
        indexed_at
    )
    VALUES (
        :mod_id,
        :index_version,
        :source_updated_at,
        :latest_summary_id,
        :latest_summary_generated_at,
        :content_hash,
        :indexed_at
    )
    """


def _fts_meta_params(row: Any) -> dict[str, Any]:
    return {
        "mod_id": int(row["mod_id"]),
        "index_version": FTS_INDEX_VERSION,
        "source_updated_at": _text(row["source_updated_at"]),
        "latest_summary_id": row["latest_summary_id"],
        "latest_summary_generated_at": row["latest_summary_generated_at"],
        "content_hash": _fts_content_hash(row),
        "indexed_at": datetime.now(UTC).isoformat(),
    }


def _fts_content_hash(row: Any) -> str:
    fields = [
        FTS_INDEX_VERSION,
        row["source_updated_at"],
        row["latest_summary_id"],
        row["latest_summary_generated_at"],
        row["title"],
        row["translated_title_zh"],
        row["external_id"],
        row["author"],
        row["category"],
        row["game"],
        row["game_domain"],
        row["url"],
        row["tags_json"],
        row["original_summary"],
        row["translated_summary"],
    ]
    payload = "\x1f".join(_text(value) for value in fields)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return "" if value is None else str(value)


def _fts_source_rows(session: Session):
    return session.execute(text(_fts_source_sql(session, "m.id IS NOT NULL"))).mappings()


def _fts_source_row(session: Session, mod_id: int):
    return (
        session.execute(text(_fts_source_sql(session, "m.id = :mod_id")), {"mod_id": mod_id})
        .mappings()
        .first()
    )


def _fts_source_sql(session: Session, where_clause: str) -> str:
    translated_title_expr = (
        "COALESCE(m.translated_title_zh, '')"
        if _mods_has_column(session, "translated_title_zh")
        else "''"
    )
    return f"""
        SELECT
            m.id AS mod_id,
            COALESCE(m.updated_at_remote, m.last_seen_at, m.first_seen_at, '') AS source_updated_at,
            MAX(s.id) AS latest_summary_id,
            MAX(s.generated_at) AS latest_summary_generated_at,
            COALESCE(m.title, '') AS title,
            {translated_title_expr} AS translated_title_zh,
            COALESCE(m.external_id, '') AS external_id,
            COALESCE(m.author, '') AS author,
            COALESCE(m.category, '') AS category,
            COALESCE(m.game, '') AS game,
            COALESCE(m.game_domain, '') AS game_domain,
            COALESCE(m.url, '') AS url,
            COALESCE(m.tags_json, '') AS tags_json,
            COALESCE(m.original_summary, '') AS original_summary,
            COALESCE(group_concat(s.content, ' '), '') AS translated_summary
        FROM mods m
        LEFT JOIN mod_summaries s ON s.mod_id = m.id
        WHERE {where_clause}
        GROUP BY m.id
        """


def _stale_mods_fts_ids(session: Session, *, limit: int) -> list[int]:
    rows = session.execute(
        text(
            f"""
            WITH latest_summary AS (
                SELECT
                    mod_id,
                    MAX(id) AS latest_summary_id,
                    MAX(generated_at) AS latest_summary_generated_at
                FROM mod_summaries
                GROUP BY mod_id
            )
            SELECT m.id AS mod_id
            FROM mods m
            LEFT JOIN mods_fts f ON f.rowid = m.id
            LEFT JOIN mods_fts_trigram t ON t.rowid = m.id
            LEFT JOIN latest_summary s ON s.mod_id = m.id
            LEFT JOIN {FTS_META_TABLE} meta ON meta.mod_id = m.id
            WHERE m.id IS NOT NULL
              AND (
                f.rowid IS NULL
                OR t.rowid IS NULL
                OR meta.mod_id IS NULL
                OR meta.index_version != :index_version
                OR COALESCE(meta.source_updated_at, '') != COALESCE(m.updated_at_remote, m.last_seen_at, m.first_seen_at, '')
                OR COALESCE(meta.latest_summary_id, 0) != COALESCE(s.latest_summary_id, 0)
                OR COALESCE(meta.latest_summary_generated_at, '') != COALESCE(s.latest_summary_generated_at, '')
                OR COALESCE(meta.content_hash, '') = ''
                OR (s.latest_summary_id IS NOT NULL AND COALESCE(TRIM(f.translated_summary), '') = '')
                OR (s.latest_summary_id IS NOT NULL AND COALESCE(TRIM(t.translated_summary), '') = '')
              )
            ORDER BY m.id
            LIMIT :limit
            """
        ),
        {"index_version": FTS_INDEX_VERSION, "limit": limit},
    ).all()
    return [int(row.mod_id) for row in rows]


def _drop_mods_fts_triggers(session: Session) -> None:
    for trigger_name in (
        "mods_fts_ai",
        "mods_fts_au",
        "mods_fts_ad",
        "mod_summaries_fts_ai",
        "mod_summaries_fts_au",
        "mod_summaries_fts_ad",
    ):
        session.exec(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))


def _ensure_mods_fts_triggers(session: Session) -> None:
    translated_new_expr = (
        "COALESCE(new.translated_title_zh, '')"
        if _mods_has_column(session, "translated_title_zh")
        else "''"
    )
    translated_m_expr = (
        "COALESCE(m.translated_title_zh, '')"
        if _mods_has_column(session, "translated_title_zh")
        else "''"
    )
    insert_new_rows = "\n".join(
        _trigger_insert_new_mod_sql(table_name, translated_new_expr) for table_name in FTS_TABLES
    )
    refresh_updated_mod = "\n".join(
        _trigger_refresh_mod_sql(table_name, translated_m_expr, "m.id = new.id")
        for table_name in FTS_TABLES
    )
    refresh_inserted_summary = "\n".join(
        _trigger_refresh_mod_sql(table_name, translated_m_expr, "m.id = new.mod_id")
        for table_name in FTS_TABLES
    )
    refresh_updated_summary = "\n".join(
        _trigger_refresh_mod_sql(table_name, translated_m_expr, "m.id IN (old.mod_id, new.mod_id)")
        for table_name in FTS_TABLES
    )
    refresh_deleted_summary = "\n".join(
        _trigger_refresh_mod_sql(table_name, translated_m_expr, "m.id = old.mod_id")
        for table_name in FTS_TABLES
    )
    delete_old_mod = "\n".join(
        f"DELETE FROM {table_name} WHERE mod_id = old.id;" for table_name in FTS_TABLES
    )
    delete_old_summary_mod = "\n".join(
        f"DELETE FROM {table_name} WHERE mod_id = old.mod_id;" for table_name in FTS_TABLES
    )
    delete_new_summary_mod = "\n".join(
        f"DELETE FROM {table_name} WHERE mod_id = new.mod_id;" for table_name in FTS_TABLES
    )
    trigger_sql = [
        f"""
        CREATE TRIGGER IF NOT EXISTS mods_fts_ai
        AFTER INSERT ON mods
        BEGIN
            {insert_new_rows}
            DELETE FROM {FTS_META_TABLE} WHERE mod_id = new.id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mods_fts_au
        AFTER UPDATE ON mods
        BEGIN
            {delete_old_mod}
            {refresh_updated_mod}
            DELETE FROM {FTS_META_TABLE} WHERE mod_id IN (old.id, new.id);
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mods_fts_ad
        AFTER DELETE ON mods
        BEGIN
            {delete_old_mod}
            DELETE FROM {FTS_META_TABLE} WHERE mod_id = old.id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mod_summaries_fts_ai
        AFTER INSERT ON mod_summaries
        BEGIN
            {delete_new_summary_mod}
            {refresh_inserted_summary}
            DELETE FROM {FTS_META_TABLE} WHERE mod_id = new.mod_id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mod_summaries_fts_au
        AFTER UPDATE ON mod_summaries
        BEGIN
            {delete_old_summary_mod}
            {delete_new_summary_mod}
            {refresh_updated_summary}
            DELETE FROM {FTS_META_TABLE} WHERE mod_id IN (old.mod_id, new.mod_id);
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mod_summaries_fts_ad
        AFTER DELETE ON mod_summaries
        BEGIN
            {delete_old_summary_mod}
            {refresh_deleted_summary}
            DELETE FROM {FTS_META_TABLE} WHERE mod_id = old.mod_id;
        END
        """,
    ]
    for statement in trigger_sql:
        session.exec(text(statement))


def _trigger_insert_new_mod_sql(table_name: str, translated_new_expr: str) -> str:
    _assert_fts_table_name(table_name)
    return f"""
            INSERT INTO {table_name}(
                rowid,
                mod_id,
                title,
                translated_title_zh,
                external_id,
                author,
                category,
                game,
                game_domain,
                url,
                tags_json,
                original_summary,
                translated_summary
            )
            VALUES (
                new.id,
                new.id,
                COALESCE(new.title, ''),
                {translated_new_expr},
                COALESCE(new.external_id, ''),
                COALESCE(new.author, ''),
                COALESCE(new.category, ''),
                COALESCE(new.game, ''),
                COALESCE(new.game_domain, ''),
                COALESCE(new.url, ''),
                COALESCE(new.tags_json, ''),
                COALESCE(new.original_summary, ''),
                ''
            );
        """


def _trigger_refresh_mod_sql(table_name: str, translated_m_expr: str, where_clause: str) -> str:
    _assert_fts_table_name(table_name)
    return f"""
            INSERT INTO {table_name}(
                rowid,
                mod_id,
                title,
                translated_title_zh,
                external_id,
                author,
                category,
                game,
                game_domain,
                url,
                tags_json,
                original_summary,
                translated_summary
            )
            SELECT
                m.id,
                m.id,
                COALESCE(m.title, ''),
                {translated_m_expr},
                COALESCE(m.external_id, ''),
                COALESCE(m.author, ''),
                COALESCE(m.category, ''),
                COALESCE(m.game, ''),
                COALESCE(m.game_domain, ''),
                COALESCE(m.url, ''),
                COALESCE(m.tags_json, ''),
                COALESCE(m.original_summary, ''),
                COALESCE(group_concat(s.content, ' '), '')
            FROM mods m
            LEFT JOIN mod_summaries s ON s.mod_id = m.id
            WHERE {where_clause}
            GROUP BY m.id;
        """


def _mods_has_column(session: Session, column: str) -> bool:
    columns = session.exec(text("PRAGMA table_info('mods')")).all()
    return any(str(row[1]) == column for row in columns)


def query_mods_fts(
    session: Session,
    *,
    keywords: list[str],
    filters: dict[str, Any],
    limit: int,
) -> list[SqliteFtsResult]:
    if not keywords or session.get_bind().dialect.name != "sqlite":
        return []
    match_query = _fts_match_query(
        keywords,
        match_all=str(filters.get("keyword_match_mode") or "").strip().lower() == "all",
    )
    if not match_query:
        return []
    if not _has_mods_fts_schema(session) and not rebuild_mods_fts(session):
        return []

    rows = []
    normalized_limit = _normalize_limit(limit)
    if _should_query_trigram(keywords):
        where, params = _filter_sql(filters, fts_table="mods_fts_trigram")
        rows = _query_mods_fts_table(
            session,
            table_name="mods_fts_trigram",
            match_query=match_query,
            where=where,
            params=params,
            limit=normalized_limit,
        )
    if not rows:
        where, params = _filter_sql(filters, fts_table="mods_fts")
        rows = _query_mods_fts_table(
            session,
            table_name="mods_fts",
            match_query=match_query,
            where=where,
            params=params,
            limit=normalized_limit,
        )
    if not rows and _contains_cjk(match_query):
        rows = _query_cjk_like_fallback(
            session,
            keywords=keywords,
            where=where,
            params=params,
            limit=normalized_limit,
            match_all=str(filters.get("keyword_match_mode") or "").strip().lower() == "all",
        )
    results: list[SqliteFtsResult] = []
    for index, row in enumerate(rows):
        mod = session.get(Mod, int(row.mod_id))
        if mod is not None:
            results.append(SqliteFtsResult(mod=mod, score=max(1, 100 - index)))
    return results


def _normalize_limit(limit: Any) -> int:
    return bounded_int(limit, default=8, minimum=1, maximum=50)


def _query_mods_fts_table(
    session: Session,
    *,
    table_name: str,
    match_query: str,
    where: str,
    params: dict[str, Any],
    limit: int,
):
    _assert_fts_table_name(table_name)
    query_params = dict(params)
    query_params["match_query"] = match_query
    query_params["limit"] = limit
    return session.execute(
        text(
            f"""
            SELECT m.id AS mod_id, bm25({table_name}) AS rank
            FROM {table_name}
            JOIN mods m ON m.id = {table_name}.mod_id
            WHERE {table_name} MATCH :match_query
              AND m.ignored = 0
              {where}
            ORDER BY rank ASC, m.first_seen_at DESC
            LIMIT :limit
            """
        ),
        query_params,
    ).all()


def _query_cjk_like_fallback(
    session: Session,
    *,
    keywords: list[str],
    where: str,
    params: dict[str, Any],
    limit: int,
    match_all: bool = False,
):
    like_clauses: list[str] = []
    fallback_params = dict(params)
    for index, keyword in enumerate(keywords):
        value = str(keyword).strip()
        if not value:
            continue
        name = f"like_keyword_{index}"
        fallback_params[name] = f"%{value}%"
        like_clauses.append(
            f"""(
                mods_fts.title LIKE :{name}
                OR mods_fts.translated_title_zh LIKE :{name}
                OR mods_fts.author LIKE :{name}
                OR mods_fts.category LIKE :{name}
                OR mods_fts.original_summary LIKE :{name}
                OR mods_fts.translated_summary LIKE :{name}
            )"""
        )
    if not like_clauses:
        return []
    fallback_params["limit"] = limit
    return session.execute(
        text(
            f"""
            SELECT m.id AS mod_id, 0 AS rank
            FROM mods_fts
            JOIN mods m ON m.id = mods_fts.mod_id
            WHERE ({(' AND ' if match_all else ' OR ').join(like_clauses)})
              AND m.ignored = 0
              {where}
            ORDER BY m.first_seen_at DESC
            LIMIT :limit
            """
        ),
        fallback_params,
    ).all()


def _has_mods_fts(session: Session) -> bool:
    return _has_fts_table(session, "mods_fts")


def _has_mods_fts_schema(session: Session) -> bool:
    return all(_has_fts_table(session, table_name) for table_name in (*FTS_TABLES, FTS_META_TABLE))


def _has_fts_table(session: Session, table_name: str) -> bool:
    try:
        row = session.execute(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = :table_name"),
            {"table_name": table_name},
        ).first()
    except OperationalError:
        return False
    return row is not None


def _fts_match_query(keywords: list[str], *, match_all: bool = False) -> str:
    terms = [str(keyword).strip() for keyword in keywords if str(keyword).strip()]
    quoted_terms = []
    for term in terms:
        escaped = term.replace('"', '""')
        quoted_terms.append(f'"{escaped}"')
    return (" AND " if match_all else " OR ").join(quoted_terms)


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _should_query_trigram(keywords: list[str]) -> bool:
    cjk_terms = [str(keyword).strip() for keyword in keywords if _contains_cjk(str(keyword))]
    if not cjk_terms:
        return False
    return all(_cjk_char_count(term) >= 3 for term in cjk_terms)


def _cjk_char_count(text: str) -> int:
    return sum(1 for char in text if "\u4e00" <= char <= "\u9fff")


def _filter_sql(filters: dict[str, Any], *, fts_table: str = "mods_fts") -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    _add_game_scope_filter(clauses, params, filters)
    _add_in_filter(clauses, params, "m.source", "source", filters.get("sources"))
    _add_not_in_filter(clauses, params, "m.source", "excluded_source", filters.get("excluded_sources"))
    _add_in_filter(clauses, params, "m.category", "category", filters.get("categories"))
    _add_identity_filter(clauses, params, filters)
    for index, tag in enumerate(filters.get("tags") or []):
        value = str(tag or "").strip()
        if not value:
            continue
        name = f"tag_{index}"
        clauses.append(f"m.tags_json LIKE :{name}")
        params[name] = f"%{value}%"
    summary_languages = [str(language).strip() for language in (filters.get("summary_languages") or []) if str(language).strip()]
    if summary_languages:
        names: list[str] = []
        for index, language in enumerate(summary_languages):
            name = f"summary_language_{index}"
            names.append(f":{name}")
            params[name] = language
        clauses.append(
            "EXISTS ("
            "SELECT 1 FROM mod_summaries s "
            "WHERE s.mod_id = m.id "
            "AND s.summary_type IN ('brief', 'introduction') "
            f"AND s.language IN ({', '.join(names)})"
            ")"
        )
    excluded_summary_languages = [
        str(language).strip() for language in (filters.get("excluded_summary_languages") or []) if str(language).strip()
    ]
    if excluded_summary_languages:
        names = []
        for index, language in enumerate(excluded_summary_languages):
            name = f"excluded_summary_language_{index}"
            names.append(f":{name}")
            params[name] = language
        clauses.append(
            "NOT EXISTS ("
            "SELECT 1 FROM mod_summaries s "
            "WHERE s.mod_id = m.id "
            "AND s.summary_type IN ('brief', 'introduction') "
            f"AND s.language IN ({', '.join(names)})"
            ")"
        )
    for index, term in enumerate(filters.get("requirement_terms") or []):
        value = str(term or "").strip()
        if not value:
            continue
        name = f"requirement_term_{index}"
        params[name] = f"%{value}%"
        clauses.append(
            f"""(
                COALESCE(m.title, '') LIKE :{name}
                OR COALESCE(m.translated_title_zh, '') LIKE :{name}
                OR COALESCE(m.tags_json, '') LIKE :{name}
                OR COALESCE(m.original_summary, '') LIKE :{name}
                OR COALESCE(m.raw_json, '') LIKE :{name}
                OR COALESCE({fts_table}.translated_summary, '') LIKE :{name}
            )"""
        )
    for index, term in enumerate(filters.get("compatibility_terms") or []):
        value = str(term or "").strip()
        if not value:
            continue
        name = f"compatibility_term_{index}"
        params[name] = f"%{value}%"
        clauses.append(
            f"""(
                COALESCE(m.title, '') LIKE :{name}
                OR COALESCE(m.translated_title_zh, '') LIKE :{name}
                OR COALESCE(m.tags_json, '') LIKE :{name}
                OR COALESCE(m.original_summary, '') LIKE :{name}
                OR COALESCE(m.raw_json, '') LIKE :{name}
                OR COALESCE({fts_table}.translated_summary, '') LIKE :{name}
            )"""
        )
    exact_title = str(filters.get("exact_title") or "").strip()
    if exact_title:
        clauses.append(
            "(LOWER(TRIM(COALESCE(m.title, ''))) = :exact_title OR "
            "LOWER(TRIM(COALESCE(m.translated_title_zh, ''))) = :exact_title)"
        )
        params["exact_title"] = " ".join(exact_title.lower().split())
    version = str(filters.get("version") or "").strip()
    if version:
        clauses.append("m.version LIKE :version")
        params["version"] = f"%{version}%"
    author = str(filters.get("author") or "").strip()
    if author:
        clauses.append("m.author LIKE :author")
        params["author"] = f"%{author}%"
    min_downloads = optional_min_metric(filters.get("min_downloads"))
    if min_downloads is not None:
        clauses.append("m.downloads >= :min_downloads")
        params["min_downloads"] = min_downloads
    min_endorsements = optional_min_metric(filters.get("min_endorsements"))
    if min_endorsements is not None:
        clauses.append("m.endorsements >= :min_endorsements")
        params["min_endorsements"] = min_endorsements
    min_views = optional_min_metric(filters.get("min_views"))
    if min_views is not None:
        clauses.append("m.views >= :min_views")
        params["min_views"] = min_views
    min_likes = optional_min_metric(filters.get("min_likes"))
    if min_likes is not None:
        clauses.append("m.likes >= :min_likes")
        params["min_likes"] = min_likes
    updated_since_days = optional_time_window(filters.get("updated_since_days"))
    if updated_since_days is not None:
        clauses.append("(m.updated_at_remote >= :updated_since_cutoff OR m.published_at_remote >= :updated_since_cutoff)")
        params["updated_since_cutoff"] = (datetime.now(UTC) - timedelta(days=updated_since_days)).isoformat()
    for key, column in {
        "updated_after": "m.updated_at_remote",
        "updated_before": "m.updated_at_remote",
        "published_after": "m.published_at_remote",
        "published_before": "m.published_at_remote",
        "created_after": "m.created_at_remote",
        "created_before": "m.created_at_remote",
    }.items():
        value = str(filters.get(key) or "").strip()
        if not value:
            continue
        clauses.append(f"{column} {'>=' if key.endswith('_after') else '<='} :{key}")
        params[key] = value
    for index, keyword in enumerate(filters.get("excluded_keywords") or []):
        value = str(keyword or "").strip()
        if not value:
            continue
        name = f"excluded_keyword_{index}"
        params[name] = f"%{value}%"
        clauses.append(
            f"""(
                COALESCE(m.title, '') NOT LIKE :{name}
                AND COALESCE(m.translated_title_zh, '') NOT LIKE :{name}
                AND COALESCE(m.author, '') NOT LIKE :{name}
                AND COALESCE(m.category, '') NOT LIKE :{name}
                AND COALESCE(m.original_summary, '') NOT LIKE :{name}
                AND COALESCE({fts_table}.translated_summary, '') NOT LIKE :{name}
            )"""
        )
    for index, title in enumerate(filters.get("exclude_titles") or []):
        value = " ".join(str(title or "").lower().split())
        if not value:
            continue
        name = f"exclude_title_{index}"
        params[name] = value
        clauses.append(
            "(LOWER(TRIM(COALESCE(m.title, ''))) != :"
            f"{name} AND LOWER(TRIM(COALESCE(m.translated_title_zh, ''))) != :{name})"
        )
    adult_content = filters.get("adult_content")
    if isinstance(adult_content, bool):
        clauses.append("m.adult_content = :adult_content")
        params["adult_content"] = int(adult_content)
    has_thumbnail = filters.get("has_thumbnail")
    if isinstance(has_thumbnail, bool):
        if has_thumbnail:
            clauses.append("(m.thumbnail_url IS NOT NULL AND m.thumbnail_url != '')")
        else:
            clauses.append("(m.thumbnail_url IS NULL OR m.thumbnail_url = '')")
    return ("\n              AND " + "\n              AND ".join(clauses) if clauses else ""), params


def _add_identity_filter(clauses: list[str], params: dict[str, Any], filters: dict[str, Any]) -> None:
    source_url = str(filters.get("source_url") or "").strip()
    external_id = str(filters.get("external_id") or "").strip()
    identity_clauses: list[str] = []
    if source_url:
        identity_clauses.append("m.url = :source_url")
        params["source_url"] = source_url
        canonical_url = url_without_query(source_url)
        if canonical_url != source_url:
            identity_clauses.append("m.url = :canonical_source_url")
            params["canonical_source_url"] = canonical_url
    if external_id:
        sources = [str(source).strip() for source in (filters.get("sources") or []) if str(source).strip()]
        if sources:
            aliases: list[str] = []
            for source in sources:
                aliases.extend(external_id_aliases(source, external_id, source_url))
            alias_names: list[str] = []
            for index, alias in enumerate(list(dict.fromkeys(aliases))):
                name = f"external_id_{index}"
                alias_names.append(f":{name}")
                params[name] = alias
            if alias_names:
                identity_clauses.append(f"m.external_id IN ({', '.join(alias_names)})")
        else:
            identity_clauses.append("m.external_id = :external_id")
            params["external_id"] = external_id
    if identity_clauses:
        clauses.append("(" + " OR ".join(identity_clauses) + ")")


def _add_in_filter(
    clauses: list[str],
    params: dict[str, Any],
    column: str,
    prefix: str,
    values: Any,
) -> None:
    normalized = [str(value).strip() for value in (values or []) if str(value).strip()]
    if not normalized:
        return
    placeholders = []
    for index, value in enumerate(normalized):
        name = f"{prefix}_{index}"
        placeholders.append(f":{name}")
        params[name] = value
    clauses.append(f"{column} IN ({', '.join(placeholders)})")


def _add_game_scope_filter(clauses: list[str], params: dict[str, Any], filters: dict[str, Any]) -> None:
    games = [str(value).strip() for value in (filters.get("games") or []) if str(value).strip()]
    game_domains = [str(value).strip() for value in (filters.get("game_domains") or []) if str(value).strip()]
    if games and game_domains:
        values = list(dict.fromkeys([*games, *game_domains]))
        placeholders = _bind_filter_values(params, "game_scope", values)
        clauses.append(f"(m.game IN ({placeholders}) OR m.game_domain IN ({placeholders}))")
        return
    if game_domains:
        placeholders = _bind_filter_values(params, "game_scope", game_domains)
        clauses.append(f"(m.game IN ({placeholders}) OR m.game_domain IN ({placeholders}))")
        return
    if games:
        _add_in_filter(clauses, params, "m.game", "game", games)


def _bind_filter_values(params: dict[str, Any], prefix: str, values: list[str]) -> str:
    placeholders = []
    for index, value in enumerate(values):
        name = f"{prefix}_{index}"
        placeholders.append(f":{name}")
        params[name] = value
    return ", ".join(placeholders)


def _add_not_in_filter(
    clauses: list[str],
    params: dict[str, Any],
    column: str,
    prefix: str,
    values: Any,
) -> None:
    normalized = [str(value).strip() for value in (values or []) if str(value).strip()]
    if not normalized:
        return
    placeholders = []
    for index, value in enumerate(normalized):
        name = f"{prefix}_{index}"
        placeholders.append(f":{name}")
        params[name] = value
    clauses.append(f"{column} NOT IN ({', '.join(placeholders)})")
