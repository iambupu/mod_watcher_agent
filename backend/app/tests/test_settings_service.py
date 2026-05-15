"""Tests for SettingsService."""

import pytest
from sqlmodel import Session, SQLModel, create_engine, select

from app.models.settings import Setting
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


class TestSettingsService:
    """Tests for SettingsService CRUD and defaults."""

    @pytest.fixture
    def service(self, session):
        return SettingsService(session)

    def test_get_returns_none_for_missing_key(self, service):
        assert service.get("nonexistent") is None

    def test_set_and_get(self, service):
        service.set("game_domain", "skyrim")
        assert service.get("game_domain") == "skyrim"

    def test_set_updates_existing(self, service):
        service.set("game_domain", "skyrim")
        service.set("game_domain", "oblivion")
        assert service.get("game_domain") == "oblivion"

    def test_get_all_returns_dict(self, service):
        service.set("key1", "value1")
        service.set("key2", "value2")
        result = service.get_all()
        assert result == {"key1": "value1", "key2": "value2"}

    def test_get_all_empty(self, service):
        assert service.get_all() == {}

    def test_set_batch(self, service):
        service.set_batch({"a": "1", "b": "2", "c": "3"})
        assert service.get_all() == {"a": "1", "b": "2", "c": "3"}

    def test_init_defaults_inserts_missing(self, service):
        service.init_defaults()
        result = service.get_all()
        for key, value in SettingsService.DEFAULTS.items():
            assert result[key] == value

    def test_init_defaults_does_not_overwrite_existing(self, service):
        service.set("game_domain", "customdomain")
        service.init_defaults()
        assert service.get("game_domain") == "customdomain"
        assert service.get("adult_policy") == "include"

    def test_updated_at_is_set_on_insert(self, service):
        service.set("test_key", "test_value")
        row = service.session.exec(
            select(Setting).where(Setting.key == "test_key")
        ).first()
        assert row.updated_at is not None
        assert "T" in row.updated_at

    def test_updated_at_is_refreshed_on_update(self, service):
        service.set("test_key", "v1")
        old = service.session.exec(
            select(Setting).where(Setting.key == "test_key")
        ).first()
        old_updated_at = old.updated_at
        service.set("test_key", "v2")
        new = service.session.exec(
            select(Setting).where(Setting.key == "test_key")
        ).first()
        assert new.updated_at != old_updated_at


class TestDefaultsMerge:
    """Tests for defaults merge logic used in GET /api/settings."""

    @pytest.fixture(name="engine")
    def fixture_engine(self):
        engine = create_engine("sqlite://", echo=False)
        SQLModel.metadata.create_all(engine)
        yield engine
        SQLModel.metadata.drop_all(engine)

    @pytest.fixture(name="session")
    def fixture_session(self, engine):
        with Session(engine) as session:
            yield session

    def test_merge_fills_missing_with_defaults(self, session):
        service = SettingsService(session)
        service.init_defaults()
        service.set("game_domain", "customdomain")
        merged = dict(service.DEFAULTS)
        merged.update(service.get_all())
        assert merged["game_domain"] == "customdomain"
        assert merged["adult_policy"] == "include"

    def test_merge_when_db_empty_returns_all_defaults(self, session):
        service = SettingsService(session)
        merged = dict(service.DEFAULTS)
        merged.update(service.get_all())
        assert merged == SettingsService.DEFAULTS
