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
        _ensure_mods_fts_triggers(session)
        session.commit()
    except OperationalError:
        session.rollback()
        return False
    return True


def rebuild_mods_fts(session: Session) -> bool:
    if not ensure_mods_fts(session):
        return False
    translated_title_expr = (
        "COALESCE(m.translated_title_zh, '')"
        if _mods_has_column(session, "translated_title_zh")
        else "''"
    )
    session.exec(text("DELETE FROM mods_fts"))
    session.exec(
        text(
            f"""
            INSERT INTO mods_fts(
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
            WHERE m.id IS NOT NULL
            GROUP BY m.id
            """
        )
    )
    session.commit()
    return True


def mods_fts_needs_rebuild(session: Session) -> bool:
    if session.get_bind().dialect.name != "sqlite":
        return False
    if not _has_mods_fts(session):
        return True
    try:
        fts_count = int(session.execute(text("SELECT COUNT(1) FROM mods_fts")).scalar_one() or 0)
        mod_count = int(
            session.execute(text("SELECT COUNT(1) FROM mods WHERE id IS NOT NULL")).scalar_one()
            or 0
        )
        stale_summary_row = session.execute(
            text(
                """
                SELECT 1
                FROM mod_summaries s
                JOIN mods m ON m.id = s.mod_id
                LEFT JOIN mods_fts f ON f.mod_id = s.mod_id
                WHERE COALESCE(TRIM(s.content), '') != ''
                  AND (
                    f.mod_id IS NULL
                    OR COALESCE(TRIM(f.translated_summary), '') = ''
                    OR instr(f.translated_summary, s.content) = 0
                  )
                LIMIT 1
                """
            )
        ).first()
    except OperationalError:
        session.rollback()
        return True
    return fts_count != mod_count or stale_summary_row is not None


def _drop_legacy_mods_fts_if_needed(session: Session) -> None:
    if not _has_mods_fts(session):
        return
    columns = session.exec(text("PRAGMA table_info('mods_fts')")).all()
    column_names = {str(row[1]) for row in columns}
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
    if required_columns.issubset(column_names):
        return
    for trigger_name in (
        "mods_fts_ai",
        "mods_fts_au",
        "mods_fts_ad",
        "mod_summaries_fts_ai",
        "mod_summaries_fts_au",
        "mod_summaries_fts_ad",
    ):
        session.exec(text(f"DROP TRIGGER IF EXISTS {trigger_name}"))
    session.exec(text("DROP TABLE IF EXISTS mods_fts"))


def refresh_mods_fts_row(session: Session, mod_id: int) -> None:
    if session.get_bind().dialect.name != "sqlite":
        return
    if not ensure_mods_fts(session):
        return
    translated_title_expr = (
        "COALESCE(m.translated_title_zh, '')"
        if _mods_has_column(session, "translated_title_zh")
        else "''"
    )
    session.execute(text("DELETE FROM mods_fts WHERE mod_id = :mod_id"), {"mod_id": mod_id})
    session.execute(
        text(
            f"""
            INSERT INTO mods_fts(
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
            WHERE m.id = :mod_id
            GROUP BY m.id
            """
        ),
        {"mod_id": mod_id},
    )


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
    trigger_sql = [
        f"""
        CREATE TRIGGER IF NOT EXISTS mods_fts_ai
        AFTER INSERT ON mods
        BEGIN
            INSERT INTO mods_fts(
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
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mods_fts_au
        AFTER UPDATE ON mods
        BEGIN
            DELETE FROM mods_fts WHERE mod_id = old.id;
            INSERT INTO mods_fts(
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
            WHERE m.id = new.id
            GROUP BY m.id;
        END
        """,
        """
        CREATE TRIGGER IF NOT EXISTS mods_fts_ad
        AFTER DELETE ON mods
        BEGIN
            DELETE FROM mods_fts WHERE mod_id = old.id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mod_summaries_fts_ai
        AFTER INSERT ON mod_summaries
        BEGIN
            DELETE FROM mods_fts WHERE mod_id = new.mod_id;
            INSERT INTO mods_fts(
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
            WHERE m.id = new.mod_id
            GROUP BY m.id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mod_summaries_fts_au
        AFTER UPDATE ON mod_summaries
        BEGIN
            DELETE FROM mods_fts WHERE mod_id = old.mod_id;
            DELETE FROM mods_fts WHERE mod_id = new.mod_id;
            INSERT INTO mods_fts(
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
            WHERE m.id IN (old.mod_id, new.mod_id)
            GROUP BY m.id;
        END
        """,
        f"""
        CREATE TRIGGER IF NOT EXISTS mod_summaries_fts_ad
        AFTER DELETE ON mod_summaries
        BEGIN
            DELETE FROM mods_fts WHERE mod_id = old.mod_id;
            INSERT INTO mods_fts(
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
            WHERE m.id = old.mod_id
            GROUP BY m.id;
        END
        """,
    ]
    for statement in trigger_sql:
        session.exec(text(statement))


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
    if not _has_mods_fts(session) and not rebuild_mods_fts(session):
        return []

    where, params = _filter_sql(filters)
    params["match_query"] = match_query
    params["limit"] = _normalize_limit(limit)
    rows = session.execute(
        text(
            f"""
            SELECT m.id AS mod_id, bm25(mods_fts) AS rank
            FROM mods_fts
            JOIN mods m ON m.id = mods_fts.mod_id
            WHERE mods_fts MATCH :match_query
              AND m.ignored = 0
              {where}
            ORDER BY rank ASC, m.first_seen_at DESC
            LIMIT :limit
            """
        ),
        params,
    ).all()
    if not rows and _contains_cjk(match_query):
        rows = _query_cjk_like_fallback(
            session,
            keywords=keywords,
            where=where,
            params=params,
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


def _query_cjk_like_fallback(
    session: Session,
    *,
    keywords: list[str],
    where: str,
    params: dict[str, Any],
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
    try:
        row = session.exec(
            text("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'mods_fts'")
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


def _filter_sql(filters: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    params: dict[str, Any] = {}
    _add_in_filter(clauses, params, "m.game", "game", filters.get("games"))
    _add_in_filter(clauses, params, "m.game_domain", "game_domain", filters.get("game_domains"))
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
                OR COALESCE(mods_fts.translated_summary, '') LIKE :{name}
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
                OR COALESCE(mods_fts.translated_summary, '') LIKE :{name}
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
                AND COALESCE(mods_fts.translated_summary, '') NOT LIKE :{name}
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
