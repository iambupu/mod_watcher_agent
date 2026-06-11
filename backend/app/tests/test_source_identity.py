# 中文注释：说明 backend/app/tests/test_source_identity.py 的模块职责，便于后续维护定位。

import hashlib

from sqlmodel import Session, SQLModel, create_engine

from app.models.mod import Mod
from app.services.source_identity import (
    canonical_external_id,
    external_id_aliases,
    find_existing_mod_by_identity,
)


def test_canonical_external_id_extracts_nexusmods_domain_scoped_id_from_url() -> None:
    assert canonical_external_id(
        "nexusmods",
        "legacy",
        "https://www.nexusmods.com/skyrimspecialedition/mods/1001?tab=files",
    ) == "skyrimspecialedition:1001"


def test_canonical_external_id_extracts_loverslab_file_id_from_url() -> None:
    assert canonical_external_id(
        "loverslab",
        "legacy",
        "https://www.loverslab.com/files/file/48837-valentina-playable-character/",
    ) == "48837"


def test_canonical_external_id_scopes_loverslab_file_id_by_game_when_available() -> None:
    assert canonical_external_id(
        "loverslab",
        "legacy",
        "https://www.loverslab.com/files/file/48837-valentina-playable-character/",
        game="X-Change Life",
    ) == "x-change-life:48837"


def test_canonical_external_id_ignores_generic_loverslab_game_domain_for_scope() -> None:
    assert canonical_external_id(
        "loverslab",
        "legacy",
        "https://www.loverslab.com/files/file/41904-barwhore/",
        game="X-Change Life",
        game_domain="loverslab",
    ) == "x-change-life:41904"


def test_loverslab_aliases_include_legacy_hashes() -> None:
    url = "https://www.loverslab.com/files/file/48837-valentina-playable-character/"
    aliases = external_id_aliases("loverslab", "48837", url, game="X-Change Life")
    assert "x-change-life:48837" in aliases
    assert "48837" in aliases
    assert hashlib.sha256(url.encode("utf-8")).hexdigest()[:32] in aliases


def test_nexusmods_aliases_include_legacy_numeric_id_for_domain_scoped_id() -> None:
    aliases = external_id_aliases("nexusmods", "skyrimspecialedition:1001")

    assert "skyrimspecialedition:1001" in aliases
    assert "1001" in aliases


def test_find_existing_mod_prefers_canonical_row_over_legacy_alias() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    url = "https://www.loverslab.com/files/file/48837-valentina-playable-character/"
    legacy_external_id = hashlib.sha256(url.encode("utf-8")).hexdigest()[:32]

    with Session(engine) as session:
        session.add_all([
            Mod(
                source="loverslab",
                external_id=legacy_external_id,
                game="LoversLab",
                title="Legacy",
                url=url,
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            ),
            Mod(
                source="loverslab",
                external_id="48837",
                game="X-Change Life",
                title="Canonical",
                url=url,
                first_seen_at="2026-01-02T00:00:00+00:00",
                last_seen_at="2026-01-02T00:00:00+00:00",
            ),
        ])
        session.commit()

        found = find_existing_mod_by_identity(session, "loverslab", legacy_external_id, url)

    assert found is not None
    assert found.external_id == "48837"


def test_find_existing_loverslab_does_not_match_same_file_id_from_different_game() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Mod(
                source="loverslab",
                external_id="skyrim-special-edition:48837",
                game="Skyrim Special Edition",
                title="Skyrim Row",
                url="https://www.loverslab.com/files/file/48837-skyrim/",
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            )
        )
        session.commit()

        found = find_existing_mod_by_identity(
            session,
            "loverslab",
            "48837",
            "https://www.loverslab.com/files/file/48837-stellar/",
            game="Stellar Blade",
        )

    assert found is None


def test_find_existing_nexusmods_keeps_same_numeric_id_separate_by_game_domain() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        session.add(
            Mod(
                source="nexusmods",
                external_id="1001",
                game="Skyrim Special Edition",
                game_domain="skyrimspecialedition",
                title="Skyrim Legacy Row",
                url="https://www.nexusmods.com/skyrimspecialedition/mods/1001",
                first_seen_at="2026-01-01T00:00:00+00:00",
                last_seen_at="2026-01-01T00:00:00+00:00",
            )
        )
        session.commit()

        stellar = find_existing_mod_by_identity(
            session,
            "nexusmods",
            "1001",
            "https://www.nexusmods.com/stellarblade/mods/1001",
        )
        skyrim = find_existing_mod_by_identity(
            session,
            "nexusmods",
            "1001",
            "https://www.nexusmods.com/skyrimspecialedition/mods/1001",
        )

    assert stellar is None
    assert skyrim is not None
    assert skyrim.title == "Skyrim Legacy Row"
