from app.services.agent.identity_inference import infer_identity_constraints, source_from_url
from app.services.agent.query_planner import infer_source_constraints


def test_infer_source_constraints_recognizes_loverslab_chinese_alias():
    constraints = infer_source_constraints("爱的实验室有什么体系mod")
    assert constraints.get("sources") == ["loverslab"]


def test_infer_source_constraints_recognizes_loverslab_chinese_exclusion():
    constraints = infer_source_constraints("排除爱的实验室，只看 nexus 的 bimbo mod")
    assert constraints.get("excluded_sources") == ["loverslab"]
    assert constraints.get("sources") == ["nexusmods"]


def test_infer_identity_constraints_recognizes_loverslab_chinese_alias_with_id():
    constraints = infer_identity_constraints("爱的实验室 mod id 12345")
    assert constraints.get("sources") == ["loverslab"]
    assert constraints.get("external_id") == "12345"


def test_identity_inference_normalizes_source_urls_and_source_hosts():
    constraints = infer_identity_constraints("看看 www.nexusmods.com/skyrimspecialedition/mods/1001?tab=files")

    assert constraints.get("source_url") == "https://www.nexusmods.com/skyrimspecialedition/mods/1001?tab=files"
    assert constraints.get("sources") == ["nexusmods"]
    assert constraints.get("external_id") == "skyrimspecialedition:1001"
    assert source_from_url(str(constraints.get("source_url"))) == "nexusmods"
