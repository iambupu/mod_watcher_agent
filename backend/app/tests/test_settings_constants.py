from app import security
from app.services import settings_payload_service
from app.settings_constants import (
    ACCESS_PROFILES,
    ACCESS_PROFILES_REQUIRING_TOKEN,
    LOVERSLAB_SEARCH_SCRAPE_ENGINES,
)


def test_settings_and_security_share_access_profile_constants():
    assert settings_payload_service.ACCESS_PROFILES is ACCESS_PROFILES
    assert security.ACCESS_PROFILES is ACCESS_PROFILES
    assert settings_payload_service.ACCESS_PROFILES_REQUIRING_TOKEN is ACCESS_PROFILES_REQUIRING_TOKEN
    assert security.ACCESS_PROFILES_REQUIRING_TOKEN is ACCESS_PROFILES_REQUIRING_TOKEN


def test_loverslab_scrape_engine_constants_are_shared_with_settings_payload():
    assert settings_payload_service.LOVERSLAB_SEARCH_SCRAPE_ENGINES is LOVERSLAB_SEARCH_SCRAPE_ENGINES
