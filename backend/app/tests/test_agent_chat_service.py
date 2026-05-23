from app.services.agent.chat_service import AgentService


def test_agent_service_keeps_session_dependency():
    service = AgentService(session=None)

    assert service.session is None
    assert hasattr(service, "chat")
    assert hasattr(service, "ask_mod_detail")
