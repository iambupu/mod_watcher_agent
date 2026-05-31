import re
from dataclasses import dataclass, field

from app.services.agent.list_utils import unique_text
from app.services.agent.semantic_inference import (
    canonical_semantic_token,
    extract_semantic_signals,
    semantic_domains_for_anchors,
    semantic_signals_from_anchors,
)
from app.services.agent.semantic_taxonomy import CHINESE_QUERY_FILLERS, STOP_WORDS

SCOPE_MARKER = "[scope]"

__all__ = [
    "SemanticQuery",
    "base_keywords",
    "canonical_semantic_terms",
    "canonical_semantic_token",
    "category_key",
    "category_match_score",
    "distinctive_query_terms",
    "infer_categories",
    "semantic_domains_for_anchors",
    "semantic_query",
    "semantic_query_from_anchors",
    "strip_scope",
    "text_score",
    "unique_terms",
]


@dataclass
class SemanticQuery:
    raw_query: str
    clean_query: str
    base_keywords: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    category_aliases: list[str] = field(default_factory=list)
    matched_concepts: list[str] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)

    @property
    def all_terms(self) -> list[str]:
        """处理当前模块的业务逻辑并返回结果。"""
        return unique_terms([*self.expanded_terms, *self.base_keywords])

    @property
    def has_semantic_terms(self) -> bool:
        """处理当前模块的业务逻辑并返回结果。"""
        return bool(self.expanded_terms or self.category_aliases)

    def search_text(self, max_terms: int = 8) -> str:
        """处理当前模块的业务逻辑并返回结果。"""
        parts = [self.clean_query, *self.expanded_terms[:max_terms]]
        return " ".join(part for part in unique_terms(parts) if part).strip()


def strip_scope(query: object) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return str(query or "").split(SCOPE_MARKER, 1)[0].strip()


def semantic_query(query: str, categories: list[str] | None = None) -> SemanticQuery:
    """处理当前模块的业务逻辑并返回结果。"""
    clean_query = strip_scope(query)
    category_text = " ".join(categories or []).lower()
    signals = extract_semantic_signals(clean_query, category_text)
    return SemanticQuery(
        raw_query=query,
        clean_query=clean_query,
        base_keywords=base_keywords(clean_query),
        expanded_terms=signals.expanded_terms,
        category_aliases=signals.category_aliases,
        matched_concepts=signals.matched_concepts,
        anchors=signals.anchors,
        domains=signals.domains,
    )


def semantic_query_from_anchors(query: str, anchors: list[str]) -> SemanticQuery:
    """基于上游 LLM 语义锚点扩展查询，不重新匹配原始文本。"""
    clean_query = strip_scope(query)
    signals = semantic_signals_from_anchors(anchors)
    return SemanticQuery(
        raw_query=query,
        clean_query=clean_query,
        base_keywords=base_keywords(clean_query),
        expanded_terms=signals.expanded_terms,
        category_aliases=signals.category_aliases,
        matched_concepts=signals.matched_concepts,
        anchors=signals.anchors,
        domains=signals.domains,
    )



def canonical_semantic_terms(values: list[str]) -> list[str]:
    """规范化语义别名，同时保持稳定输入顺序。"""
    return unique_terms([canonical_semantic_token(value) for value in values])



def base_keywords(query: str) -> list[str]:
    """处理当前模块的业务逻辑并返回结果。"""
    clean_query = strip_scope(query).lower()
    tokens = []
    for raw_token in re.split(r"[^\w\u4e00-\u9fff]+", clean_query):
        token = _clean_keyword_token(raw_token)
        if token and token not in STOP_WORDS:
            if re.search(r"[a-z0-9]", token) and re.search(r"[\u4e00-\u9fff]", token):
                tokens.extend(_mixed_keyword_parts(token))
                continue
            tokens.append(token)
    return unique_terms(tokens)


def _clean_keyword_token(token: str) -> str:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    cleaned = str(token or "").strip().lower()
    if not cleaned:
        return ""
    for filler in CHINESE_QUERY_FILLERS:
        cleaned = cleaned.replace(filler, "")
    return cleaned.strip()


def _mixed_keyword_parts(token: str) -> list[str]:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    parts: list[str] = []
    parts.extend(re.findall(r"[a-z0-9][a-z0-9_-]*", token))
    parts.extend(re.findall(r"[\u4e00-\u9fff]+", token))
    return [part for part in parts if part and part not in STOP_WORDS]


def distinctive_query_terms(query: str) -> list[str]:
    """处理当前模块的业务逻辑并返回结果。"""
    return [
        token
        for token in base_keywords(query)
        if len(token) >= 2 and re.fullmatch(r"[a-z0-9][a-z0-9_-]*", token)
    ]


def infer_categories(
    query: str,
    available_categories: list[str],
    existing: list[str] | None = None,
    semantic: SemanticQuery | None = None,
) -> list[str]:
    """处理当前模块的业务逻辑并返回结果。"""
    selected = list(existing or [])
    semantic = semantic or semantic_query(query, selected)
    if not semantic.category_aliases and not semantic.expanded_terms and not semantic.base_keywords:
        return selected
    selected_keys = {category_key(value) for value in selected}
    scored: list[tuple[int, int, str]] = []
    for category in available_categories:
        key = category_key(category)
        if key in selected_keys:
            continue
        score = category_match_score(category, semantic)
        if score > 0:
            scored.append((score, -len(scored), category))
    for _, _, category in sorted(scored, reverse=True)[:5]:
        selected.append(category)
        selected_keys.add(category_key(category))
    return selected


def category_key(value: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", value.lower())


def category_match_score(category: str, semantic: SemanticQuery) -> int:
    """处理当前模块的业务逻辑并返回结果。"""
    key = category_key(category)
    spaced = category.lower()
    score = 0
    for alias in semantic.category_aliases:
        alias_key = category_key(alias)
        if alias_key and alias_key in key:
            score += 6
    for term in semantic.expanded_terms:
        term_key = category_key(term)
        if len(term_key) < 4:
            continue
        if term_key and (term_key in key or term.lower() in spaced):
            score += 3
    for keyword in semantic.base_keywords:
        keyword_key = category_key(keyword)
        if keyword_key and keyword_key in key:
            score += 2
    return score


def text_score(query: str, fields: list[str | None], categories: list[str] | None = None) -> int:
    """处理当前模块的业务逻辑并返回结果。"""
    semantic = semantic_query(query, categories)
    tokens = semantic.all_terms
    if not tokens:
        return 0
    haystack = " ".join(field or "" for field in fields).lower()
    score = 0
    for token in tokens:
        if token in haystack:
            score += 2 if token in semantic.expanded_terms else 1
    clean_query = semantic.clean_query.lower()
    if clean_query and clean_query in haystack:
        score += 3
    return score


def unique_terms(values: list[str]) -> list[str]:
    """处理当前模块的业务逻辑并返回结果。"""
    return unique_text(re.sub(r"\s+", " ", str(value or "").strip().lower()) for value in values)
