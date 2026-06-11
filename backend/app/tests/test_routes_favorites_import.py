# 中文注释：说明 backend/app/tests/test_routes_favorites_import.py 的模块职责，便于后续维护定位。

import hashlib

from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.db import get_session
from app.main import app as fastapi_app
from app.models.favorite import Favorite
from app.models.mod import Mod


def test_create_favorite_can_clear_existing_tags_with_explicit_empty_array() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="skyrimspecialedition:1001",
            game="Skyrim Special Edition",
            title="Test Mod",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
            first_seen_at="2026-01-01T00:00:00Z",
            last_seen_at="2026-01-01T00:00:00Z",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(
            Favorite(
                mod_id=mod.id,
                user_tags_json='["old"]',
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        session.commit()
        mod_id = mod.id

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        response = client.post(
            "/api/favorites",
            json={"mod_id": mod_id, "user_tags_json": "[]", "user_note": None},
        )

        assert response.status_code == 201
        assert response.json()["user_tags_json"] == "[]"
        assert response.json()["user_note"] is None
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_creates_mod_and_favorite() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        response = client.post(
            "/api/favorites/import",
            json={
                "source": "nexusmods",
                "external_id": "1001",
                "game": "Skyrim Special Edition",
                "game_domain": "skyrimspecialedition",
                "title": "Test Mod",
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                "author": "Mod Author",
                "user_note": "captured from Chrome",
                "user_tags_json": '["chrome"]',
            },
        )

        assert response.status_code == 201
        body = response.json()
        assert body["user_note"] == "captured from Chrome"
        assert body["user_tags_json"] == '["chrome"]'
        assert body["mod"]["source"] == "nexusmods"
        assert body["mod"]["external_id"] == "skyrimspecialedition:1001"
        assert body["mod"]["game_domain"] == "skyrimspecialedition"

        with Session(engine) as session:
            mods = session.exec(select(Mod)).all()
            favorites = session.exec(select(Favorite)).all()
        assert len(mods) == 1
        assert len(favorites) == 1
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_can_clear_existing_tags_with_explicit_empty_string() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        mod = Mod(
            source="nexusmods",
            external_id="skyrimspecialedition:1001",
            game="Skyrim Special Edition",
            game_domain="skyrimspecialedition",
            title="Test Mod",
            url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
            first_seen_at="2026-01-01T00:00:00Z",
            last_seen_at="2026-01-01T00:00:00Z",
        )
        session.add(mod)
        session.commit()
        session.refresh(mod)
        session.add(
            Favorite(
                mod_id=mod.id,
                user_tags_json='["old"]',
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            )
        )
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        response = client.post(
            "/api/favorites/import",
            json={
                "source": "nexusmods",
                "external_id": "1001",
                "game": "Skyrim Special Edition",
                "game_domain": "skyrimspecialedition",
                "title": "Test Mod",
                "url": "https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                "user_tags_json": "",
            },
        )

        assert response.status_code == 201
        assert response.json()["user_tags_json"] == ""
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_is_idempotent_and_refreshes_mod_fields() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        payload = {
            "source": "loverslab",
            "external_id": "48837",
            "game": "LoversLab",
            "title": "Old Title",
            "url": "https://www.loverslab.com/files/file/48837-old-title/",
        }
        first = client.post("/api/favorites/import", json=payload)
        second = client.post(
            "/api/favorites/import",
            json={
                **payload,
                "title": "Valentina playable character",
                "url": "https://www.loverslab.com/files/file/48837-valentina-playable-character/",
            },
        )

        assert first.status_code == 201
        assert second.status_code == 201
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["mod"]["title"] == "Valentina playable character"

        with Session(engine) as session:
            assert len(session.exec(select(Mod)).all()) == 1
            assert len(session.exec(select(Favorite)).all()) == 1
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_reuses_loverslab_search_hash_record() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    url = "https://www.loverslab.com/files/file/48837-valentina-playable-character/"
    legacy_external_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    with Session(engine) as session:
        session.add(
            Mod(
                source="loverslab",
                external_id=legacy_external_id,
                game="LoversLab",
                game_domain="loverslab",
                title="Search Result Title",
                url=url,
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            )
        )
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        response = client.post(
            "/api/favorites/import",
            json={
                "source": "loverslab",
                "external_id": "48837",
                "game": "LoversLab",
                "title": "Valentina playable character",
                "url": url,
            },
        )

        assert response.status_code == 201
        assert response.json()["mod"]["external_id"] == "48837"
        with Session(engine) as session:
            mods = session.exec(select(Mod)).all()
            favorites = session.exec(select(Favorite)).all()
        assert len(mods) == 1
        assert len(favorites) == 1
        assert mods[0].external_id == "48837"
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_prefers_existing_canonical_row_when_legacy_duplicate_exists() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    url = "https://www.loverslab.com/files/file/48837-valentina-playable-character/"
    legacy_external_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    with Session(engine) as session:
        session.add_all([
            Mod(
                source="loverslab",
                external_id=legacy_external_id,
                game="LoversLab",
                game_domain="loverslab",
                title="Legacy Search Result",
                url=url,
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            ),
            Mod(
                source="loverslab",
                external_id="48837",
                game="LoversLab",
                game_domain=None,
                title="Canonical Result",
                url=url,
                first_seen_at="2026-01-02T00:00:00+00:00",
                last_seen_at="2026-01-02T00:00:00+00:00",
            ),
        ])
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        response = client.post(
            "/api/favorites/import",
            json={
                "source": "loverslab",
                "external_id": "48837",
                "game": "LoversLab",
                "title": "Valentina playable character",
                "url": url,
            },
        )

        assert response.status_code == 201
        assert response.json()["mod"]["external_id"] == "48837"
        with Session(engine) as session:
            mods = session.exec(select(Mod).where(Mod.source == "loverslab")).all()
            favorites = session.exec(select(Favorite)).all()
        assert len(mods) == 2
        assert len(favorites) == 1
        assert response.json()["mod_id"] == next(mod.id for mod in mods if mod.external_id == "48837")
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_does_not_overwrite_existing_game_when_page_game_is_unknown() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    url = "https://www.loverslab.com/files/file/48837-valentina-playable-character/"

    with Session(engine) as session:
        session.add(
            Mod(
                source="loverslab",
                external_id="48837",
                game="X-Change Life",
                game_domain="loverslab",
                title="Valentina playable character",
                url=url,
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            )
        )
        session.commit()

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        response = client.post(
            "/api/favorites/import",
            json={
                "source": "loverslab",
                "external_id": "48837",
                "game": "",
                "title": "Valentina playable character updated",
                "url": url,
            },
        )

        assert response.status_code == 201
        assert response.json()["mod"]["game"] == "X-Change Life"
        assert response.json()["mod"]["title"] == "Valentina playable character updated"
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_decodes_html_entities_from_loverslab_metadata() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        response = client.post(
            "/api/favorites/import",
            json={
                "source": "loverslab",
                "external_id": "41904",
                "game": "X-Change Life",
                "title": "BarWhore",
                "url": "https://www.loverslab.com/files/file/41904-barwhore/",
                "category": "Gameplay Changes &amp; Events",
                "original_summary": "Gameplay &amp; events update",
            },
        )

        assert response.status_code == 201
        assert response.json()["mod"]["external_id"] == "x-change-life:41904"
        assert response.json()["mod"]["category"] == "Gameplay Changes & Events"
        assert response.json()["mod"]["original_summary"] == "Gameplay & events update"
    finally:
        fastapi_app.dependency_overrides.clear()


def test_import_favorite_keeps_same_loverslab_file_id_separate_by_game() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    def override_get_session():
        with Session(engine) as session:
            yield session

    fastapi_app.dependency_overrides[get_session] = override_get_session
    try:
        client = TestClient(fastapi_app)
        first = client.post(
            "/api/favorites/import",
            json={
                "source": "loverslab",
                "external_id": "48837",
                "game": "Skyrim Special Edition",
                "title": "Skyrim File",
                "url": "https://www.loverslab.com/files/file/48837-skyrim-file/",
            },
        )
        second = client.post(
            "/api/favorites/import",
            json={
                "source": "loverslab",
                "external_id": "48837",
                "game": "Stellar Blade",
                "title": "Stellar File",
                "url": "https://www.loverslab.com/files/file/48837-stellar-file/",
            },
        )

        assert first.status_code == 201
        assert second.status_code == 201
        with Session(engine) as session:
            mods = session.exec(select(Mod).where(Mod.source == "loverslab")).all()
        assert {mod.external_id for mod in mods} == {
            "skyrim-special-edition:48837",
            "stellar-blade:48837",
        }
        assert {mod.title for mod in mods} == {"Skyrim File", "Stellar File"}
    finally:
        fastapi_app.dependency_overrides.clear()


def test_chrome_extension_origin_is_allowed_by_default_for_api_cors() -> None:
    client = TestClient(fastapi_app)
    response = client.options(
        "/api/favorites/import",
        headers={
            "Origin": "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-mod-watcher-token",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "chrome-extension://aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )
