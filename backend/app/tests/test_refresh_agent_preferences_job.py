# 中文注释：说明 backend/app/tests/test_refresh_agent_preferences_job.py 的模块职责，便于后续维护定位。

from app.jobs.refresh_agent_preferences import _profile_refresh_job_result


def test_profile_refresh_job_result_tolerates_invalid_summary_counts():
    result = _profile_refresh_job_result(
        {
            "favorite_summary": {"favorite_count": "bad", "top_games": ["Stellar Blade"]},
            "conversation_summary": {"message_count": "-5", "top_games": "Skyrim"},
        }
    )

    assert result["items_scanned"] == 0
    assert result["items_matched"] == 1


def test_profile_refresh_job_result_handles_non_dict_payload():
    result = _profile_refresh_job_result(None)  # type: ignore[arg-type]

    assert result["items_scanned"] == 0
    assert result["items_matched"] == 0
