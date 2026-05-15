"""Tests for APScheduler jobs using WatchRule."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.watch_rule import WatchRule


@pytest.fixture(name="db_engine")
def db_engine_fixture():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    yield engine


@pytest.fixture(name="db_session")
def db_session_fixture(db_engine):
    with Session(db_engine) as session:
        yield session


def _make_rule(
    session: Session,
    name: str,
    enabled: bool = True,
    source: str = "nexusmods",
) -> WatchRule:
    rule = WatchRule(
        name=name,
        enabled=enabled,
        source=source,
        source_config_json="{}",
        filters_json="{}",
        notification_json='{"enabled": false, "mode": "daily_digest", "channels": []}',
        created_at="2025-01-01T00:00:00",
        updated_at="2025-01-01T00:00:00",
    )
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return rule


class TestJobsSkipDisabled:

    @pytest.mark.asyncio
    async def test_disabled_rules_are_not_processed(self, db_session, db_engine):
        """Disabled watch rules should be skipped by the discovery job."""
        _make_rule(db_session, "enabled-rule", enabled=True)
        _make_rule(db_session, "disabled-rule", enabled=False)

        from app.jobs.discover_new_mods import discover_new_mods

        with patch("app.jobs.discover_new_mods.engine", db_engine):
            with patch("app.services.discovery_service.DiscoveryService.discover_from_rule",
                       new_callable=AsyncMock) as mock_discover:
                mock_discover.return_value = []

                results = db_session.exec(select(WatchRule)).all()
                assert len(results) == 2

                result = await discover_new_mods()

        assert "enabled-rule" in result
        assert "disabled-rule" not in result
        assert mock_discover.call_count == 1


class TestJobsUseWatchRule:

    @pytest.mark.asyncio
    async def test_job_queries_watch_rules_table(self, db_session, db_engine):
        """The discovery job must query the single WatchRule table."""
        _make_rule(db_session, "my-rule", enabled=True, source="nexusmods")

        from app.jobs.discover_new_mods import discover_new_mods

        with patch("app.jobs.discover_new_mods.engine", db_engine):
            with patch("app.services.discovery_service.DiscoveryService.discover_from_rule",
                       new_callable=AsyncMock) as mock_discover:
                mock_discover.return_value = []

                result = await discover_new_mods()

        assert "my-rule" in result
        assert result["my-rule"] == 0
        assert mock_discover.call_count == 1

    @pytest.mark.asyncio
    async def test_job_uses_discovery_service(self, db_session, db_engine):
        """The job must call DiscoveryService.discover_from_rule for each enabled rule."""
        _make_rule(db_session, "rule-a", enabled=True)
        _make_rule(db_session, "rule-b", enabled=True)

        from app.jobs.discover_new_mods import discover_new_mods

        with patch("app.jobs.discover_new_mods.engine", db_engine):
            with patch("app.services.discovery_service.DiscoveryService.discover_from_rule",
                       new_callable=AsyncMock) as mock_discover:
                mock_discover.return_value = []

                result = await discover_new_mods()

        assert result == {"rule-a": 0, "rule-b": 0}
        assert mock_discover.call_count == 2
