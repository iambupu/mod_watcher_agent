from typing import Any

from sqlmodel import Session

from app.jobs.scheduler import register_jobs
from app.services.settings_payload_service import (
    SettingsPayloadError,
    prepare_settings_update,
    settings_import_items,
)
from app.services.settings_service import SettingsService


def apply_settings_update(session: Session, items: dict[str, str]) -> SettingsService:
    service = SettingsService(session)
    if items:
        prepared = prepare_settings_update(service, items)
        service.set_batch(prepared)
        register_jobs(session)
    return service


def import_settings_payload(session: Session, data: dict[str, Any]) -> int:
    service = SettingsService(session)
    items = settings_import_items(data)
    if items:
        prepared = prepare_settings_update(service, items)
        service.set_batch(prepared)
        register_jobs(session)
    return len(items)


__all__ = [
    "SettingsPayloadError",
    "apply_settings_update",
    "import_settings_payload",
]
