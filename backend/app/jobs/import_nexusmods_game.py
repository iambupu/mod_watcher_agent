from sqlmodel import Session

from app.adapters.nexusmods import NexusModsAdapter
from app.db import engine
from app.services.discovery_service import DiscoveryService
from app.services.settings_service import SettingsService


async def import_nexusmods_game(
    game_domain_name: str,
    *,
    batch_size: int = 100,
    max_batches: int | None = None,
) -> dict:
    """Import all available NexusMods metadata for one game in batches."""
    normalized_domain = game_domain_name.strip().lower()
    total_fetched = 0
    total_created = 0
    total_updated = 0
    expected_total: int | None = None
    batches = 0

    with Session(engine) as session:
        nexus_api_key = SettingsService(session).get("nexus_api_key") or ""
    adapter = NexusModsAdapter(api_key=nexus_api_key)

    async for batch in adapter.iter_game_mod_batches(
        normalized_domain,
        batch_size=batch_size,
        max_batches=max_batches,
    ):
        items = batch.items
        expected_total = batch.total_count
        total_fetched += len(items)
        batches += 1
        with Session(engine) as session:
            result = DiscoveryService(session).upsert_mod_items(items)
        total_created += int(result["created"])
        total_updated += int(result["updated"])

    if expected_total is None:
        expected_total = 0
    if total_fetched < expected_total:
        raise RuntimeError(
            "NexusMods import incomplete: "
            f"fetched {total_fetched} of {expected_total} mods for {normalized_domain}"
        )

    return {
        "game_domain_name": normalized_domain,
        "batch_size": batch_size,
        "total_count": expected_total,
        "batches": batches,
        "fetched": total_fetched,
        "created": total_created,
        "updated": total_updated,
        "items_scanned": total_fetched,
        "items_matched": total_created,
    }
