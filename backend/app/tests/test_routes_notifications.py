from fastapi.testclient import TestClient
from sqlalchemy import inspect, text
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app import db as app_db
from app.db import get_session
from app.main import app as fastapi_app
from app.models.notification import Notification


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _notification(subject: str, created_at: str, read: bool = False) -> Notification:
    return Notification(
        channel="telegram",
        recipient="chat",
        subject=subject,
        body=f"{subject} body",
        status="sent",
        sent_at=created_at,
        created_at=created_at,
        read=read,
    )


def test_notifications_list_and_read_state() -> None:
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    client = TestClient(fastapi_app)

    try:
        with Session(engine) as session:
            session.add(_notification("old-read", "2026-05-18T00:00:00+00:00", read=True))
            session.add(_notification("new-unread", "2026-05-19T00:00:00+00:00"))
            session.add(_notification("older-unread", "2026-05-17T00:00:00+00:00"))
            session.commit()

        list_response = client.get("/api/notifications")
        assert list_response.status_code == 200
        payload = list_response.json()
        assert payload["total"] == 3
        assert [item["subject"] for item in payload["items"]] == [
            "new-unread",
            "old-read",
            "older-unread",
        ]
        assert payload["items"][0]["read"] is False

        unread_response = client.get("/api/notifications/unread-count")
        assert unread_response.status_code == 200
        assert unread_response.json() == {"count": 2}

        mark_response = client.post(
            "/api/notifications/mark-read",
            json={"ids": [payload["items"][0]["id"], payload["items"][0]["id"]]},
        )
        assert mark_response.status_code == 200
        assert mark_response.json() == {"updated": 1}

        bool_id_response = client.post(
            "/api/notifications/mark-read",
            json={"ids": [True]},
        )
        assert bool_id_response.status_code == 422

        non_positive_id_response = client.post(
            "/api/notifications/mark-read",
            json={"ids": [0]},
        )
        assert non_positive_id_response.status_code == 422

        unread_after_one = client.get("/api/notifications/unread-count")
        assert unread_after_one.json() == {"count": 1}

        mark_all_response = client.post("/api/notifications/mark-all-read")
        assert mark_all_response.status_code == 200
        assert mark_all_response.json() == {"updated": 1}

        unread_after_all = client.get("/api/notifications/unread-count")
        assert unread_after_all.json() == {"count": 0}

        assert client.get("/api/notifications?offset=-1").status_code == 422
        assert client.get("/api/notifications?limit=0").status_code == 422
        assert client.get("/api/notifications?limit=201").status_code == 422
    finally:
        fastapi_app.dependency_overrides.clear()


def test_lightweight_migration_adds_notification_read_column(monkeypatch) -> None:
    engine = _make_engine()
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE watch_rules (id INTEGER PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE notifications (id INTEGER PRIMARY KEY, channel TEXT NOT NULL)"))
        conn.execute(text("CREATE TABLE mods (id INTEGER PRIMARY KEY, source TEXT NOT NULL, external_id TEXT NOT NULL)"))

    monkeypatch.setattr(app_db, "engine", engine)
    app_db._apply_lightweight_migrations()

    inspector = inspect(engine)
    notification_columns = {column["name"] for column in inspector.get_columns("notifications")}
    watch_rule_columns = {column["name"] for column in inspector.get_columns("watch_rules")}

    assert "read" in notification_columns
    assert "interval_minutes" in watch_rule_columns
