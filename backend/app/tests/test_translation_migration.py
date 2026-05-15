"""Tests for summary_language migration fix in SettingsService.init_defaults().

These tests verify the translation migration behavior:
  - Old installs had summary_language defaulting to "en"
  - New installs should default to "zh-CN"
  - init_defaults() must override "en" → "zh-CN" but not override "zh-CN" → "zh-CN"
  - Non-summary user settings must never be overwritten

NOTE: Test 1 will fail until the init_defaults() bug is fixed (currently only
inserts when value is None, doesn't handle the "en" → "zh-CN" migration).
"""

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.services.settings_service import SettingsService


@pytest.fixture(name="engine")
def fixture_engine():
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    yield engine
    SQLModel.metadata.drop_all(engine)


@pytest.fixture(name="session")
def fixture_session(engine):
    with Session(engine) as session:
        yield session


class TestTranslationMigration:
    """Tests for summary_language migration in init_defaults()."""

    @pytest.fixture
    def service(self, session):
        return SettingsService(session)

    def test_migration_overrides_en_to_zh_cn(self, service):
        """When summary_language is "en" (old default), init_defaults() must
        override it to "zh-CN"."""
        service.set("summary_language", "en")
        service.init_defaults()
        assert service.get("summary_language") == "zh-CN"

    def test_migration_preserves_zh_cn(self, service):
        """When summary_language is already "zh-CN", init_defaults() must not
        change it."""
        service.set("summary_language", "zh-CN")
        service.init_defaults()
        assert service.get("summary_language") == "zh-CN"

    def test_migration_preserves_user_game_domain(self, service):
        """User-modified non-summary settings must survive init_defaults()
        unchanged, even when summary_language migration runs."""
        service.set("game_domain", "oblivion")
        service.set("summary_language", "en")
        service.init_defaults()
        assert service.get("game_domain") == "oblivion"
