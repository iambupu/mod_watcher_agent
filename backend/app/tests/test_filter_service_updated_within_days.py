# 中文注释：说明 backend/app/tests/test_filter_service_updated_within_days.py 的模块职责，便于后续维护定位。

from __future__ import annotations

import json

from sqlmodel import Session, SQLModel, create_engine

from app.services.filter_service import FilterService


class _Rule:
    def __init__(self, mode: str):
        self.filters_json = json.dumps(
            {
                "updatedWithinDays": 7,
                "llmFilter": {
                    "enabled": True,
                    "prompt": "",
                    "mode": mode,
                    "minConfidence": 0.7,
                },
            }
        )


def _build_session() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_updated_within_days_parse_failure_rejected_in_must_pass() -> None:
    svc = FilterService()
    mods = [
        {
            "source": "nexusmods",
            "external_id": "1",
            "title": "Bad Date",
            "original_summary": "",
            "url": "https://example.com",
            "updated_at_remote": "not-a-date",
        }
    ]
    with _build_session() as session:
        result = svc.apply_filters(_Rule("must_pass"), mods, session)

    assert result == []
    assert svc.rejected_reasons.get("updated_within_days_parse_failed") == 1


def test_updated_within_days_parse_failure_passes_in_assist_only_with_hint() -> None:
    svc = FilterService()
    mods = [
        {
            "source": "nexusmods",
            "external_id": "1",
            "title": "Bad Date",
            "original_summary": "",
            "url": "https://example.com",
            "updated_at_remote": "not-a-date",
        }
    ]
    with _build_session() as session:
        result = svc.apply_filters(_Rule("assist_only"), mods, session)

    assert len(result) == 1
    assert svc.rejected_reasons.get("updated_within_days_parse_failed") == 1


def test_updated_within_days_accepts_z_suffix_timestamps() -> None:
    svc = FilterService()
    mods = [
        {
            "source": "nexusmods",
            "external_id": "1",
            "title": "Z Date",
            "original_summary": "",
            "url": "https://example.com",
            "updated_at_remote": "2999-05-30T00:00:00Z",
        }
    ]
    with _build_session() as session:
        result = svc.apply_filters(_Rule("must_pass"), mods, session)

    assert len(result) == 1
    assert svc.rejected_reasons.get("updated_within_days_parse_failed") is None
