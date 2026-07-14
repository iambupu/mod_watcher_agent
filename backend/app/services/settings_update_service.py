# 中文注释：封装后端服务层的设置更新副作用逻辑。

from typing import Any

from sqlmodel import Session

from app.jobs.scheduler import register_jobs
from app.runtime_paths import RuntimePathError, build_runtime_paths, save_database_path_selection
from app.security import invalidate_runtime_policy_cache
from app.services.settings_payload_service import (
    SettingsPayloadError,
    prepare_settings_update,
    settings_import_items,
)
from app.services.settings_service import SettingsService


def _commit_settings_change(session: Session) -> None:
    try:
        register_jobs(session)
        session.commit()
    except Exception:
        session.rollback()
        raise
    invalidate_runtime_policy_cache()


def apply_settings_update(session: Session, items: dict[str, str]) -> SettingsService:
    service = SettingsService(session)
    if items:
        prepared = prepare_settings_update(service, items)
        database_path = prepared.pop("database_path", None)
        if database_path is not None:
            try:
                save_database_path_selection(build_runtime_paths(), database_path)
            except RuntimePathError as exc:
                raise SettingsPayloadError(422, str(exc)) from exc
        if prepared:
            service.set_batch(prepared, commit=False)
            _commit_settings_change(session)
    return service


def import_settings_payload(session: Session, data: dict[str, Any]) -> int:
    service = SettingsService(session)
    items = settings_import_items(data)
    if items:
        prepared = prepare_settings_update(service, items)
        database_path = prepared.pop("database_path", None)
        if database_path is not None:
            try:
                save_database_path_selection(build_runtime_paths(), database_path)
            except RuntimePathError as exc:
                raise SettingsPayloadError(422, str(exc)) from exc
        if prepared:
            service.set_batch(prepared, commit=False)
            _commit_settings_change(session)
    return len(items)


__all__ = [
    "SettingsPayloadError",
    "apply_settings_update",
    "import_settings_payload",
]
