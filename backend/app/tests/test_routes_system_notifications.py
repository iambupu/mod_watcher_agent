from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.db import get_session
from app.main import app as fastapi_app
from app.services.system_notification_service import SystemNotificationService


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def test_system_notification_bulk_id_routes_reject_bool_and_non_positive_ids() -> None:
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    client = TestClient(fastapi_app)

    try:
        with Session(engine) as session:
            event = SystemNotificationService(session).create_event("custom_event", "标题", "正文")

        assert client.post("/api/system-notifications/mark-seen", json={"event_ids": [True]}).status_code == 422
        assert client.post("/api/system-notifications/mark-seen", json={"event_ids": [0]}).status_code == 422
        assert client.post(
            "/api/system-notifications/dispatch-windows",
            json={"event_ids": [False]},
        ).status_code == 422

        mark_response = client.post(
            "/api/system-notifications/mark-seen",
            json={"event_ids": [event.id]},
        )
        assert mark_response.status_code == 200
        assert mark_response.json() == {"updated": 1}
    finally:
        fastapi_app.dependency_overrides.clear()
