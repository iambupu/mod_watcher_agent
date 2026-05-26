from app.services.agent.slot_constraint_inference import (
    infer_absolute_date_constraints,
    infer_numeric_constraints,
    infer_time_window,
    query_without_absolute_date_terms,
    query_without_metric_terms,
)


def test_slot_constraint_inference_extracts_metric_thresholds_without_keyword_noise():
    query = "Skyrim Special Edition bimbo mod 下载至少 1,000"

    assert infer_numeric_constraints(query) == {"min_downloads": 1000}
    cleaned = query_without_metric_terms(query)
    assert "1,000" not in cleaned
    assert "下载至少" not in cleaned
    assert "bimbo" in cleaned


def test_slot_constraint_inference_extracts_time_windows_and_cleans_terms():
    query = "最近七天的 Skyrim Special Edition bimbo mod"

    assert infer_time_window(query) == {"updated_since_days": 7}


def test_slot_constraint_inference_extracts_absolute_date_ranges_and_cleans_terms():
    query = "2024年发布的 Skyrim Special Edition body mod"

    assert infer_absolute_date_constraints(query) == {
        "published_after": "2024-01-01T00:00:00+00:00",
        "published_before": "2024-12-31T23:59:59+00:00",
    }
    cleaned = query_without_absolute_date_terms(query)
    assert "2024" not in cleaned
    assert "发布" not in cleaned
    assert "body" in cleaned
