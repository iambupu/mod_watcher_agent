import re

_SPECIFIC_MOD_QUESTION_PATTERN = re.compile(
    r"(如何|怎么样|怎么|支持|兼容|安装|风险|情况|是否|吗|\?|？|详情|介绍|解析|物理|前置|依赖|冲突|版本|作者|更新)",
    flags=re.IGNORECASE,
)


def has_specific_mod_question_marker(text: str) -> bool:
    """Return whether text asks for details about one concrete mod."""
    return bool(_SPECIFIC_MOD_QUESTION_PATTERN.search(str(text or "")))
