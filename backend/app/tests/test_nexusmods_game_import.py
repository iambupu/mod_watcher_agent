import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import app.models  # noqa: F401
from app.adapters.nexusmods import NexusModsBatch, RateLimitError
from app.db import get_session
from app.main import app as fastapi_app
from app.models.job_run import JobRun
from app.models.mod import Mod
from app.models.mod_item import ModItem


def _make_engine():
    return create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


def _mod_item(source_id: str, title: str, downloads: int = 10) -> ModItem:
    return ModItem(
        source_id=source_id,
        source="nexusmods",
        name=title,
        game="Skyrim Special Edition",
        url=f"https://www.nexusmods.com/skyrimspecialedition/mods/{source_id}",
        summary="Summary",
        author="Author",
        downloads=downloads,
        endorsements=5,
        likes=0,
        categories=["Weapons"],
        tags=["tag-a", "tag-b"],
        thumbnail_url="https://example.test/thumb.jpg",
        raw={
            "modId": source_id,
            "version": "1.0",
            "game": {
                "domainName": "skyrimspecialedition",
                "name": "Skyrim Special Edition",
            },
        },
    )


def _raw_nexus_mod(source_id: int) -> dict:
    return {
        "modId": source_id,
        "name": f"Mod {source_id}",
        "summary": "Summary",
        "author": "Author",
        "category": "Weapons",
        "game": {
            "domainName": "skyrimspecialedition",
            "name": "Skyrim Special Edition",
        },
        "downloads": 10,
        "endorsements": 5,
        "adultContent": False,
        "tags": [],
    }


@pytest.mark.asyncio
async def test_nexusmods_game_batches_continue_when_api_returns_less_than_requested(monkeypatch):
    from app.adapters.nexusmods import NexusModsAdapter

    adapter = NexusModsAdapter(api_key="test")
    offsets: list[int] = []

    async def fake_graphql_query(query, variables):
        offsets.append(variables["offset"])
        start = int(variables["offset"])
        nodes = [_raw_nexus_mod(i) for i in range(start + 1, start + 81)]
        return {"data": {"mods": {"nodes": nodes, "totalCount": 160}}}

    monkeypatch.setattr(adapter, "_graphql_query", fake_graphql_query)

    batches = [
        batch
        async for batch in adapter.iter_game_mod_batches(
            "skyrimspecialedition",
            batch_size=100,
        )
    ]

    assert offsets == [0, 80]
    assert [batch.offset for batch in batches] == [0, 80]
    assert sum(len(batch.items) for batch in batches) == 160
    assert {batch.total_count for batch in batches} == {160}


@pytest.mark.asyncio
async def test_import_nexusmods_game_persists_batches(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeAdapter:
        def __init__(self, api_key: str | None = None):
            self.api_key = api_key

        async def iter_game_mod_batches(self, game_domain_name, *, batch_size, max_batches):
            assert game_domain_name == "skyrimspecialedition"
            assert batch_size == 2
            assert max_batches == 3
            yield NexusModsBatch(
                items=[_mod_item("1", "First Mod"), _mod_item("2", "Second Mod")],
                total_count=3,
                offset=0,
            )
            yield NexusModsBatch(
                items=[_mod_item("2", "Second Mod Updated", downloads=20)],
                total_count=3,
                offset=2,
            )

    monkeypatch.setattr("app.jobs.import_nexusmods_game.engine", engine)
    monkeypatch.setattr("app.jobs.import_nexusmods_game.NexusModsAdapter", FakeAdapter)

    from app.jobs.import_nexusmods_game import import_nexusmods_game

    result = await import_nexusmods_game(
        "SkyrimSpecialEdition",
        batch_size=2,
        max_batches=3,
    )

    assert result["game_domain_name"] == "skyrimspecialedition"
    assert result["batches"] == 2
    assert result["total_count"] == 3
    assert result["items_scanned"] == 3
    assert result["created"] == 2
    assert result["updated"] == 1
    assert result["items_matched"] == 2

    with Session(engine) as session:
        mods = session.exec(select(Mod).order_by(Mod.external_id)).all()
        assert [mod.title for mod in mods] == ["First Mod", "Second Mod Updated"]
        assert mods[1].downloads == 20
        assert json.loads(mods[0].tags_json) == ["tag-a", "tag-b"]


@pytest.mark.asyncio
async def test_import_nexusmods_game_tolerates_invalid_upsert_counts(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeAdapter:
        def __init__(self, api_key: str | None = None):
            self.api_key = api_key

        async def iter_game_mod_batches(self, game_domain_name, *, batch_size, max_batches):
            yield NexusModsBatch(items=[_mod_item("1", "First Mod")], total_count=1, offset=0)

    class FakeDiscoveryService:
        def __init__(self, session):
            self.session = session

        def upsert_mod_items(self, items):
            return {"created": "bad", "updated": "-3"}

    monkeypatch.setattr("app.jobs.import_nexusmods_game.engine", engine)
    monkeypatch.setattr("app.jobs.import_nexusmods_game.NexusModsAdapter", FakeAdapter)
    monkeypatch.setattr("app.jobs.import_nexusmods_game.DiscoveryService", FakeDiscoveryService)

    from app.jobs.import_nexusmods_game import import_nexusmods_game

    result = await import_nexusmods_game("skyrimspecialedition")

    assert result["created"] == 0
    assert result["updated"] == 0
    assert result["items_scanned"] == 1


@pytest.mark.asyncio
async def test_import_nexusmods_game_fails_when_total_count_not_reached(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeAdapter:
        def __init__(self, api_key: str | None = None):
            self.api_key = api_key

        async def iter_game_mod_batches(self, game_domain_name, *, batch_size, max_batches):
            yield NexusModsBatch(
                items=[_mod_item("1", "First Mod")],
                total_count=2,
                offset=0,
            )

    monkeypatch.setattr("app.jobs.import_nexusmods_game.engine", engine)
    monkeypatch.setattr("app.jobs.import_nexusmods_game.NexusModsAdapter", FakeAdapter)

    from app.jobs.import_nexusmods_game import import_nexusmods_game

    with pytest.raises(RuntimeError, match="fetched 1 of 2"):
        await import_nexusmods_game("skyrimspecialedition", batch_size=1)


@pytest.mark.asyncio
async def test_import_nexusmods_game_propagates_rate_limit(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)

    class FakeAdapter:
        def __init__(self, api_key: str | None = None):
            self.api_key = api_key

        async def iter_game_mod_batches(self, game_domain_name, *, batch_size, max_batches):
            raise RateLimitError("NexusMods API rate limit exceeded")
            yield

    monkeypatch.setattr("app.jobs.import_nexusmods_game.engine", engine)
    monkeypatch.setattr("app.jobs.import_nexusmods_game.NexusModsAdapter", FakeAdapter)

    from app.jobs.import_nexusmods_game import import_nexusmods_game

    with pytest.raises(RateLimitError):
        await import_nexusmods_game("skyrimspecialedition")


def test_import_nexusmods_game_route_queues_job(monkeypatch):
    engine = _make_engine()
    SQLModel.metadata.create_all(engine)
    queued_job_ids: list[int] = []

    def override_get_session():
        with Session(engine) as session:
            yield session

    def fake_enqueue(job_run_id, handler):
        queued_job_ids.append(job_run_id)

    monkeypatch.setattr("app.services.job_queue_service.enqueue_job_run", fake_enqueue)
    fastapi_app.dependency_overrides[get_session] = override_get_session
    client = TestClient(fastapi_app)

    try:
        response = client.post(
            "/api/jobs/nexusmods/import-game",
            json={"game_domain_name": "SkyrimSpecialEdition", "batch_size": 50},
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "queued"
        assert queued_job_ids == [data["job_id"]]

        with Session(engine) as session:
            job = session.get(JobRun, data["job_id"])
            assert job is not None
            assert job.job_name == "nexusmods_import_game"
            metadata = json.loads(job.metadata_json)
            assert metadata["game_domain_name"] == "skyrimspecialedition"
            assert metadata["batch_size"] == 50
    finally:
        fastapi_app.dependency_overrides.clear()
