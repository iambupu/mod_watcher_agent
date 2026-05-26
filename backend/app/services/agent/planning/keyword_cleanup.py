import re
from urllib.parse import urlparse

from app.services.agent.semantic_search import category_match_score, semantic_query
from app.services.agent.slot_aliases import SOURCE_ALIASES, SUMMARY_LANGUAGE_ALIASES
from app.services.game_alias_service import alias_key


def drop_source_keywords(keywords: list[str]) -> list[str]:
    source_aliases = {alias_key(alias) for alias in SOURCE_ALIASES}
    source_values = {alias_key(source) for source in SOURCE_ALIASES.values()}
    return [keyword for keyword in keywords if alias_key(keyword) not in source_aliases | source_values]


def drop_excluded_keywords(keywords: list[str], excluded_keywords: list[str]) -> list[str]:
    excluded_keys = {alias_key(keyword) for keyword in excluded_keywords if alias_key(keyword)}
    if not excluded_keys:
        return keywords
    return [keyword for keyword in keywords if alias_key(keyword) not in excluded_keys]


def drop_excluded_categories(categories: list[str], excluded_keywords: list[str]) -> list[str]:
    if not excluded_keywords:
        return categories
    excluded_semantic = semantic_query(" ".join(excluded_keywords))
    return [
        category
        for category in categories
        if category_match_score(category, excluded_semantic) <= 0
    ]


def query_without_excluded_terms(query: str, excluded_keywords: list[str]) -> str:
    if not excluded_keywords:
        return query
    cleaned = query
    for keyword in excluded_keywords:
        if keyword:
            cleaned = re.sub(re.escape(keyword), " ", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def drop_author_keywords(keywords: list[str], author: str | None) -> list[str]:
    author_key = alias_key(author or "")
    if not author_key:
        return keywords
    return [keyword for keyword in keywords if not _keyword_matches_author(keyword, author_key)]


def drop_metric_keywords(keywords: list[str], metrics: dict[str, int | None]) -> list[str]:
    metric_numbers = {str(value) for value in metrics.values() if value is not None}
    metric_words = {
        "download",
        "downloads",
        "downloaded",
        "endorsement",
        "endorsements",
        "view",
        "views",
        "like",
        "likes",
        "下载",
        "下载量",
        "背书",
        "点赞",
        "浏览",
        "浏览量",
        "喜欢",
        "喜欢数",
        "数",
        "至少",
        "不少于",
        "不低于",
        "超过",
        "大于",
        "以上",
        "min",
        "minimum",
        "more",
        "over",
    }
    return [
        keyword
        for keyword in keywords
        if keyword not in metric_numbers and alias_key(keyword) not in {alias_key(word) for word in metric_words}
    ]


def drop_sort_keywords(keywords: list[str], sort_field: str) -> list[str]:
    sort_words = {
        "recent",
        "recently",
        "latest",
        "new",
        "newest",
        "updated",
        "update",
        "popular",
        "popularity",
        "top",
        "most",
        "highest",
        "best",
        "download",
        "downloads",
        "downloaded",
        "endorsement",
        "endorsements",
        "endorsed",
        "endorse",
        "rated",
        "rating",
        "view",
        "views",
        "like",
        "likes",
        "最新",
        "最近",
        "更新",
        "热门",
        "火",
        "最多",
        "最高",
        "下载",
        "下载量",
        "背书",
        "点赞",
        "浏览",
        "浏览量",
        "喜欢",
    }
    if sort_field == "relevance":
        sort_words -= {"best"}
    blocked = {alias_key(word) for word in sort_words}
    return [keyword for keyword in keywords if alias_key(keyword) not in blocked]


def drop_adult_keywords(keywords: list[str], adult_content: bool | None) -> list[str]:
    if adult_content is None:
        return keywords
    adult_words = {
        "adult",
        "non",
        "nonadult",
        "non-adult",
        "nsfw",
        "sfw",
        "safe",
        "safe-for-work",
        "r18",
        "18+",
        "no",
        "without",
        "exclude",
        "excluding",
        "成人",
        "成人内容",
        "非成人",
        "不要成人",
        "不要成人内容",
    }
    blocked = {alias_key(word) for word in adult_words}
    return [keyword for keyword in keywords if alias_key(keyword) not in blocked]


def drop_time_window_keywords(keywords: list[str], updated_since_days: int | None) -> list[str]:
    if updated_since_days is None:
        return keywords
    time_numbers = {
        str(updated_since_days),
        str(updated_since_days // 7) if updated_since_days % 7 == 0 else "",
        str(updated_since_days // 30) if updated_since_days % 30 == 0 else "",
    }
    time_words = {
        "最近",
        "近",
        "过去",
        "天",
        "日",
        "周",
        "星期",
        "个月",
        "月",
        "last",
        "past",
        "within",
        "day",
        "days",
        "week",
        "weeks",
        "month",
        "months",
    }
    blocked = {alias_key(word) for word in time_words}
    return [
        keyword
        for keyword in keywords
        if keyword not in time_numbers and alias_key(keyword) not in blocked
    ]


def drop_absolute_date_keywords(keywords: list[str], date_ranges: dict[str, str | None]) -> list[str]:
    date_values = {
        value
        for value in date_ranges.values()
        if value
    }
    date_numbers: set[str] = set()
    for value in date_values:
        date_numbers.add(value[:4])
        date_numbers.add(value[:10])
    date_words = {
        "更新",
        "发布",
        "创建",
        "以后",
        "之后",
        "以来",
        "以前",
        "之前",
        "年",
        "updated",
        "update",
        "published",
        "publish",
        "created",
        "create",
        "after",
        "since",
        "before",
        "until",
    }
    blocked = {alias_key(word) for word in date_words}
    return [keyword for keyword in keywords if keyword not in date_numbers and alias_key(keyword) not in blocked]


def drop_tag_keywords(keywords: list[str], tags: list[str]) -> list[str]:
    if not tags:
        return keywords
    tag_keys = {alias_key(tag) for tag in tags if alias_key(tag)}
    tag_words = {alias_key(value) for value in ["tag", "tags", "tagged", "标签", "带", "包含", "含有", "with"]}
    return [
        keyword
        for keyword in keywords
        if alias_key(keyword) not in tag_keys | tag_words
    ]


def drop_requirement_keywords(keywords: list[str], requirement_terms: list[str]) -> list[str]:
    if not requirement_terms:
        return keywords
    term_keys = {alias_key(term) for term in requirement_terms if alias_key(term)}
    requirement_words = {
        alias_key(value)
        for value in [
            "requirement",
            "requirements",
            "dependency",
            "dependencies",
            "requires",
            "requiring",
            "require",
            "need",
            "needs",
            "needed",
            "script",
            "extender",
            "script extender",
            "skyrim script extender",
            "前置",
            "依赖",
            "需要",
            "要求",
            "兼容",
            "冲突",
        ]
    }
    return [keyword for keyword in keywords if alias_key(keyword) not in term_keys | requirement_words]


def drop_compatibility_keywords(keywords: list[str], compatibility_terms: list[str]) -> list[str]:
    if not compatibility_terms:
        return keywords
    term_keys = {alias_key(term) for term in compatibility_terms if alias_key(term)}
    compatibility_words = {
        alias_key(value)
        for value in [
            "compatible",
            "compatibility",
            "support",
            "supports",
            "for",
            "runtime",
            "version",
            "兼容",
            "支持",
            "适配",
            "版本",
        ]
    }
    return [keyword for keyword in keywords if alias_key(keyword) not in term_keys | compatibility_words]


def drop_summary_language_keywords(keywords: list[str], summary_languages: list[str]) -> list[str]:
    if not summary_languages:
        return keywords
    language_words = {
        alias_key(value)
        for value in [
            *SUMMARY_LANGUAGE_ALIASES.keys(),
            *SUMMARY_LANGUAGE_ALIASES.values(),
            "摘要",
            "介绍",
            "说明",
            "summary",
            "summaries",
            "intro",
            "introduction",
            "description",
            "translated",
            "translation",
        ]
    }
    return [keyword for keyword in keywords if alias_key(keyword) not in language_words]


def drop_version_keywords(keywords: list[str], version: str | None) -> list[str]:
    if not version:
        return keywords
    version_keys = {alias_key(version), alias_key(f"v{version}")}
    version_words = {alias_key(value) for value in ["version", "versions", "版本", "v"]}
    return [
        keyword
        for keyword in keywords
        if alias_key(keyword) not in version_keys | version_words
    ]


def drop_identity_keywords(
    keywords: list[str],
    external_id: str | None,
    source_url: str | None,
) -> list[str]:
    if not external_id and not source_url:
        return keywords
    identity_keys = {
        alias_key(value)
        for value in [
            "id",
            "mod id",
            "external id",
            "source id",
            "file",
            "resource",
            "http",
            "https",
            "www",
            "com",
            "mod",
            "mods",
            "nexus",
            "nexuss",
            "nexusmods",
            "loverslab",
        ]
    }
    if external_id:
        identity_keys.add(alias_key(external_id))
        if ":" in external_id:
            identity_keys.update(alias_key(part) for part in external_id.split(":") if part)
    if source_url:
        parsed = urlparse(source_url)
        identity_keys.add(alias_key(source_url))
        identity_keys.add(alias_key(parsed.netloc))
        for part in parsed.path.split("/"):
            if part:
                identity_keys.add(alias_key(part))
    return [keyword for keyword in keywords if alias_key(keyword) not in identity_keys]


def _keyword_matches_author(keyword: str, author_key: str) -> bool:
    keyword_key = alias_key(keyword)
    if not keyword_key:
        return False
    return keyword_key in author_key or author_key in keyword_key
