from app.services.agent.filter_value_utils import (
    optional_min_metric,
    optional_time_window,
)


def test_optional_metric_and_time_window_share_integer_rules():
    assert optional_min_metric("1,200") == 1200
    assert optional_min_metric("-2") == 0
    assert optional_min_metric("bad") is None
    assert optional_time_window("400") == 365
    assert optional_time_window("-2") == 1
    assert optional_time_window("bad") is None
