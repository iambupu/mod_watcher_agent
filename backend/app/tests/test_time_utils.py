from datetime import UTC, datetime, timedelta, timezone

from app.utils.time import parse_utc_datetime


def test_parse_utc_datetime_handles_empty_and_invalid_values():
    assert parse_utc_datetime(None) is None
    assert parse_utc_datetime("") is None
    assert parse_utc_datetime("not a date") is None


def test_parse_utc_datetime_normalizes_z_and_naive_values_to_utc():
    assert parse_utc_datetime("2026-05-30T12:00:00Z") == datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    assert parse_utc_datetime("2026-05-30T12:00:00") == datetime(2026, 5, 30, 12, 0, tzinfo=UTC)


def test_parse_utc_datetime_converts_offset_values_to_utc():
    value = parse_utc_datetime("2026-05-30T20:00:00+08:00")

    assert value == datetime(2026, 5, 30, 12, 0, tzinfo=UTC)
    assert parse_utc_datetime(datetime(2026, 5, 30, 20, 0, tzinfo=timezone(timedelta(hours=8)))) == value
