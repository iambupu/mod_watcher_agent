import json

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.services.agent.llm_config_service import get_llm_config
from app.services.settings_service import SettingsService


@pytest.fixture(name="service")
def fixture_service():
    engine = create_engine("sqlite://", echo=False)
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield SettingsService(session)


def test_unknown_provider_override_is_rejected(service):
    service.set(
        "llm_providers_json",
        json.dumps(
            [
                {
                    "provider": "openai",
                    "enabled": True,
                    "priority": 1,
                    "model": "gpt-4o-mini",
                    "api_key": "key",
                    "base_url": "https://api.openai.com/v1",
                }
            ]
        ),
    )

    with pytest.raises(ValueError, match="Unknown or disabled LLM provider override"):
        get_llm_config(service, provider_override="missing", model_override="wrong-model")
