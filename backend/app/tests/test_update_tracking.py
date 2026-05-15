"""Tests for UpdateTrackingService."""

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.update_event import ModUpdateEvent
from app.services.update_tracking_service import UpdateTrackingService


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


class TestUpdateTrackingService:
    """Tests for UpdateTrackingService query and management."""

    @pytest.fixture
    def service(self, session):
        return UpdateTrackingService(session)

    def _create_event(
        self,
        session,
        mod_id=1,
        favorite_id=1,
        old_version="1.0",
        new_version="2.0",
        detected_at="2025-01-01T00:00:00",
        seen=False,
    ):
        event = ModUpdateEvent(
            mod_id=mod_id,
            favorite_id=favorite_id,
            old_version=old_version,
            new_version=new_version,
            detected_at=detected_at,
            seen=seen,
        )
        session.add(event)
        session.commit()
        return event

    # ── get_events filtering ──────────────────────────────────────────

    def test_get_events_all(self, service, session):
        self._create_event(session, mod_id=1, detected_at="2025-01-01T00:00:00")
        self._create_event(session, mod_id=2, detected_at="2025-01-02T00:00:00")
        items, total = service.get_events()
        assert total == 2
        assert len(items) == 2

    def test_get_events_filter_by_mod_id(self, service, session):
        self._create_event(session, mod_id=1)
        self._create_event(session, mod_id=2)
        self._create_event(session, mod_id=1)
        items, total = service.get_events(mod_id=1)
        assert total == 2
        assert all(e.mod_id == 1 for e in items)

    def test_get_events_filter_by_favorite_id(self, service, session):
        self._create_event(session, favorite_id=10)
        self._create_event(session, favorite_id=20)
        self._create_event(session, favorite_id=10)
        items, total = service.get_events(favorite_id=10)
        assert total == 2
        assert all(e.favorite_id == 10 for e in items)

    def test_get_events_filter_by_seen(self, service, session):
        self._create_event(session, seen=False, detected_at="2025-01-01T00:00:00")
        self._create_event(session, seen=True, detected_at="2025-01-02T00:00:00")
        self._create_event(session, seen=False, detected_at="2025-01-03T00:00:00")
        items, total = service.get_events(seen=False)
        assert total == 2
        assert all(not e.seen for e in items)

    def test_get_events_combined_filters(self, service, session):
        self._create_event(session, mod_id=1, favorite_id=10, seen=False, detected_at="2025-01-01T00:00:00")
        self._create_event(session, mod_id=1, favorite_id=20, seen=False, detected_at="2025-01-02T00:00:00")
        self._create_event(session, mod_id=1, favorite_id=10, seen=True, detected_at="2025-01-03T00:00:00")
        items, total = service.get_events(mod_id=1, favorite_id=10, seen=False)
        assert total == 1
        assert items[0].favorite_id == 10
        assert not items[0].seen

    # ── get_events pagination ─────────────────────────────────────────

    def test_get_events_pagination(self, service, session):
        for i in range(10):
            self._create_event(session, detected_at=f"2025-01-{i+1:02d}T00:00:00")
        items, total = service.get_events(offset=0, limit=3)
        assert total == 10
        assert len(items) == 3

    def test_get_events_pagination_offset(self, service, session):
        for i in range(5):
            self._create_event(session, detected_at=f"2025-01-{i+1:02d}T00:00:00")
        items, total = service.get_events(offset=3, limit=5)
        assert total == 5
        assert len(items) == 2

    # ── get_events ordering ───────────────────────────────────────────

    def test_get_events_ordering_desc(self, service, session):
        e1 = self._create_event(session, detected_at="2025-01-01T00:00:00")
        e3 = self._create_event(session, detected_at="2025-01-03T00:00:00")
        e2 = self._create_event(session, detected_at="2025-01-02T00:00:00")
        items, _ = service.get_events()
        assert [e.id for e in items] == [e3.id, e2.id, e1.id]

    # ── mark_seen ─────────────────────────────────────────────────────

    def test_mark_seen_sets_flag(self, service, session):
        event = self._create_event(session, seen=False)
        updated = service.mark_seen(event.id)
        assert updated.seen is True

    def test_mark_seen_commits(self, service, session):
        event = self._create_event(session, seen=False)
        service.mark_seen(event.id)
        refreshed = session.get(ModUpdateEvent, event.id)
        assert refreshed.seen is True

    def test_mark_seen_nonexistent_raises(self, service):
        with pytest.raises(ValueError, match="not found"):
            service.mark_seen(9999)

    # ── get_unseen_count ──────────────────────────────────────────────

    def test_get_unseen_count_zero_when_all_seen(self, service, session):
        self._create_event(session, seen=True)
        self._create_event(session, seen=True)
        assert service.get_unseen_count() == 0

    def test_get_unseen_count_counts_unseen(self, service, session):
        self._create_event(session, seen=False, detected_at="2025-01-01T00:00:00")
        self._create_event(session, seen=True, detected_at="2025-01-02T00:00:00")
        self._create_event(session, seen=False, detected_at="2025-01-03T00:00:00")
        assert service.get_unseen_count() == 2

    # ── empty dataset ─────────────────────────────────────────────────

    def test_get_events_empty(self, service):
        items, total = service.get_events()
        assert items == []
        assert total == 0

    def test_get_unseen_count_empty(self, service):
        assert service.get_unseen_count() == 0
