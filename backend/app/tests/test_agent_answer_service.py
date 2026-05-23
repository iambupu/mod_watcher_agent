from app.services.agent.answer_service import build_fallback_answer, parse_next_steps
from app.services.agent.schemas import AgentModMatch


def test_build_fallback_answer_lists_titles_and_sources():
    matches = [
        AgentModMatch(
            id=1,
            title="XXTB Suit",
            source="nexusmods",
            game="Stellar Blade",
            author=None,
            version=None,
            url="https://example.com",
            updated_at_remote=None,
            score=5,
        )
    ]

    answer = build_fallback_answer(matches)

    assert "XXTB Suit" in answer
    assert "nexusmods" in answer


def test_parse_next_steps_accepts_json_array():
    steps = parse_next_steps('["想看 XXTB Suit 的安装风险吗？", "要按下载量重排这些 Stellar Blade 结果吗？"]')

    assert steps == ["想看 XXTB Suit 的安装风险吗？", "要按下载量重排这些 Stellar Blade 结果吗？"]


def test_parse_next_steps_accepts_numbered_lines():
    steps = parse_next_steps("1. 展开 MGO 的兼容性说明\n2. 只看 NexusMods 的最近更新结果")

    assert steps == ["展开 MGO 的兼容性说明", "只看 NexusMods 的最近更新结果"]


def test_parse_next_steps_extracts_question_from_objects():
    steps = parse_next_steps(
        """[
        {"question": "THICCified Racer 的下载量和好评数是否真的很高？"},
        {"question": "Better Blaster Cell 是否会影响武器平衡性？"}
        ]"""
    )

    assert steps == ["THICCified Racer 的下载量和好评数是否真的很高？", "Better Blaster Cell 是否会影响武器平衡性？"]


def test_parse_next_steps_extracts_question_from_single_quoted_object_lines():
    steps = parse_next_steps(
        """{'question': "THICCified Racer's High 的下载量和好评数是否真的很高？ "}
        {'question': 'Better Blaster Cell 是否会影响游戏原有的武器平衡性？ '}"""
    )

    assert steps == [
        "THICCified Racer's High 的下载量和好评数是否真的很高？",
        "Better Blaster Cell 是否会影响游戏原有的武器平衡性？",
    ]
