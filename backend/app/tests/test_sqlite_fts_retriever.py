from app.services.agent.retrievers import sqlite_fts_retriever


class _FakeDialect:
    name = "sqlite"


class _FakeBind:
    dialect = _FakeDialect()


class _FakeSession:
    def __init__(self, refreshed: list[int]) -> None:
        self.refreshed = refreshed
        self.commit_snapshots: list[int] = []

    def get_bind(self) -> _FakeBind:
        return _FakeBind()

    def commit(self) -> None:
        self.commit_snapshots.append(len(self.refreshed))


class _RecordingSession:
    def __init__(self) -> None:
        self.executed: list[str] = []

    def execute(self, statement, _params=None):
        self.executed.append(str(statement))

    def exec(self, statement):
        self.executed.append(str(statement))


def test_repair_stale_mods_fts_commits_large_repairs_in_smaller_batches(monkeypatch):
    refreshed: list[int] = []
    session = _FakeSession(refreshed)

    monkeypatch.setattr(sqlite_fts_retriever, "ensure_mods_fts", lambda session: True)
    monkeypatch.setattr(
        sqlite_fts_retriever,
        "_stale_mods_fts_ids",
        lambda session, *, limit: list(range(1, 251)),
    )
    monkeypatch.setattr(
        sqlite_fts_retriever,
        "_refresh_mods_fts_row",
        lambda session, mod_id: refreshed.append(mod_id),
    )

    repaired = sqlite_fts_retriever.repair_stale_mods_fts(session, limit=250)

    assert repaired == 250
    assert session.commit_snapshots == [100, 200, 250]


def test_refresh_deletes_fts_rows_by_indexed_rowid(monkeypatch):
    session = _RecordingSession()
    monkeypatch.setattr(
        sqlite_fts_retriever,
        "_insert_single_mods_fts_sql",
        lambda _session, _table_name: "SELECT 1",
    )
    monkeypatch.setattr(sqlite_fts_retriever, "_upsert_mods_fts_meta", lambda _session, _mod_id: None)

    sqlite_fts_retriever._refresh_mods_fts_row(session, 42)

    delete_statements = [statement for statement in session.executed if statement.startswith("DELETE FROM")]
    assert len(delete_statements) == 2
    assert all("WHERE rowid = :mod_id" in statement for statement in delete_statements)


def test_fts_triggers_delete_rows_by_indexed_rowid(monkeypatch):
    session = _RecordingSession()
    monkeypatch.setattr(sqlite_fts_retriever, "_mods_has_column", lambda _session, _name: True)

    sqlite_fts_retriever._ensure_mods_fts_triggers(session)

    trigger_sql = "\n".join(session.executed)
    assert "WHERE rowid = old.id" in trigger_sql
    assert "WHERE rowid = old.mod_id" in trigger_sql
    assert "WHERE rowid = new.mod_id" in trigger_sql
    assert all(
        f"DELETE FROM {table_name} WHERE mod_id" not in trigger_sql
        for table_name in sqlite_fts_retriever.FTS_TABLES
    )


def test_filter_sql_preserves_structured_filter_clauses_and_bindings():
    sql, params = sqlite_fts_retriever._filter_sql(
        {
            "games": ["Skyrim Special Edition"],
            "sources": ["nexusmods"],
            "excluded_sources": ["loverslab"],
            "categories": ["Body"],
            "tags": ["CBBE"],
            "summary_languages": ["zh-CN"],
            "excluded_summary_languages": ["ja-JP"],
            "requirement_terms": ["SKSE"],
            "compatibility_terms": ["AE"],
            "exact_title": "  Bimbo   Body  ",
            "version": "1.2",
            "author": "Ousnius",
            "min_downloads": 1000,
            "min_likes": 20,
            "updated_after": "2024-01-01T00:00:00+00:00",
            "excluded_keywords": ["old"],
            "exclude_titles": ["Legacy Body"],
            "adult_content": True,
            "has_thumbnail": False,
        }
    )

    for fragment in (
        "m.game IN (:game_0)",
        "m.source IN (:source_0)",
        "m.source NOT IN (:excluded_source_0)",
        "m.category IN (:category_0)",
        "s.language IN (:summary_language_0)",
        "s.language IN (:excluded_summary_language_0)",
        "m.downloads >= :min_downloads",
        "m.likes >= :min_likes",
        "m.updated_at_remote >= :updated_after",
        "m.adult_content = :adult_content",
        "(m.thumbnail_url IS NULL OR m.thumbnail_url = '')",
    ):
        assert fragment in sql
    assert params == {
        "game_0": "Skyrim Special Edition",
        "source_0": "nexusmods",
        "excluded_source_0": "loverslab",
        "category_0": "Body",
        "tag_0": "%CBBE%",
        "summary_language_0": "zh-CN",
        "excluded_summary_language_0": "ja-JP",
        "requirement_term_0": "%SKSE%",
        "compatibility_term_0": "%AE%",
        "exact_title": "bimbo body",
        "version": "%1.2%",
        "author": "%Ousnius%",
        "min_downloads": 1000,
        "min_likes": 20,
        "updated_after": "2024-01-01T00:00:00+00:00",
        "excluded_keyword_0": "%old%",
        "exclude_title_0": "legacy body",
        "adult_content": 1,
    }


def test_filter_sql_uses_requested_fts_table_for_term_filters():
    sql, params = sqlite_fts_retriever._filter_sql(
        {
            "requirement_terms": ["SKSE"],
            "compatibility_terms": ["AE"],
            "excluded_keywords": ["old"],
        },
        fts_table="mods_fts_trigram",
    )

    assert sql.count("mods_fts_trigram.translated_summary") == 3
    assert params == {
        "requirement_term_0": "%SKSE%",
        "compatibility_term_0": "%AE%",
        "excluded_keyword_0": "%old%",
    }
