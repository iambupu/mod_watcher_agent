from collections import defaultdict

SOURCE_ALIASES = {
    "nexusmods": "nexusmods",
    "nexus mods": "nexusmods",
    "nexus": "nexusmods",
    "loverslab": "loverslab",
    "lovers lab": "loverslab",
    "爱的实验室": "loverslab",
    "爱实验室": "loverslab",
    "爱の实验室": "loverslab",
    "爱之实验室": "loverslab",
    "llab": "loverslab",
    "ll": "loverslab",
}

SOURCE_HOST_ALIASES = {
    "nexusmods": ["nexusmods.com", "www.nexusmods.com"],
    "loverslab": ["loverslab.com", "www.loverslab.com"],
}

SUMMARY_LANGUAGE_ALIASES = {
    "中文": "zh-CN",
    "简体中文": "zh-CN",
    "汉语": "zh-CN",
    "汉化": "zh-CN",
    "chinese": "zh-CN",
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "英文": "en",
    "英语": "en",
    "english": "en",
    "en": "en",
    "日文": "ja-JP",
    "日语": "ja-JP",
    "japanese": "ja-JP",
    "ja": "ja-JP",
    "ja-jp": "ja-JP",
}


def source_aliases_by_source() -> dict[str, list[str]]:
    grouped: defaultdict[str, list[str]] = defaultdict(list)
    for alias, source in SOURCE_ALIASES.items():
        grouped[source].append(alias)
    return dict(grouped)


def normalize_source_alias(value: object) -> str:
    text = str(value or "").strip().lower()
    return SOURCE_ALIASES.get(text, text)
