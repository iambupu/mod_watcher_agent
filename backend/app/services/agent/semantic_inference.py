import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.list_utils import unique_text
from app.services.agent.semantic_taxonomy import SEMANTIC_RULES
from app.services.agent.slot_aliases import SOURCE_ALIASES


@dataclass
class SemanticSignals:
    expanded_terms: list[str] = field(default_factory=list)
    category_aliases: list[str] = field(default_factory=list)
    matched_concepts: list[str] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CompositionalInference:
    anchor: str
    signal: Callable[[str], bool]
    required_anchors: frozenset[str] = frozenset()
    any_anchor: frozenset[str] = frozenset()
    blocked_anchors: frozenset[str] = frozenset()


def extract_semantic_signals(query_text: str, category_text: str = "") -> SemanticSignals:
    expanded: list[str] = []
    aliases: list[str] = []
    concepts: list[str] = []
    anchors: list[str] = []
    domains: list[str] = []
    lower_query = query_text.lower()
    lower_categories = category_text.lower()
    for rule in SEMANTIC_RULES:
        markers = [str(marker).lower() for marker in rule.get("markers", [])]
        if any(
            _marker_matches_text(marker, lower_query) or _marker_matches_text(marker, lower_categories)
            for marker in markers
        ):
            _append_semantic_rule_signal(
                rule,
                concepts=concepts,
                expanded=expanded,
                aliases=aliases,
                anchors=anchors,
                domains=domains,
            )
    _apply_compositional_semantic_inferences(
        lower_query,
        concepts=concepts,
        expanded=expanded,
        aliases=aliases,
        anchors=anchors,
        domains=domains,
    )
    return SemanticSignals(
        expanded_terms=unique_terms(expanded),
        category_aliases=unique_terms(aliases),
        matched_concepts=unique_terms(concepts),
        anchors=unique_terms(anchors),
        domains=unique_terms(domains),
    )


def semantic_signals_from_anchors(anchors: list[str]) -> SemanticSignals:
    signals = SemanticSignals()
    for anchor in anchors:
        _append_named_semantic_rule(
            str(anchor or "").strip().lower(),
            concepts=signals.matched_concepts,
            expanded=signals.expanded_terms,
            aliases=signals.category_aliases,
            anchors=signals.anchors,
            domains=signals.domains,
        )
    signals.expanded_terms = unique_terms(signals.expanded_terms)
    signals.category_aliases = unique_terms(signals.category_aliases)
    signals.matched_concepts = unique_terms(signals.matched_concepts)
    signals.anchors = unique_terms(signals.anchors)
    signals.domains = unique_terms(signals.domains)
    return signals


def semantic_domains_for_anchors(anchors: list[str]) -> list[str]:
    """基于规范锚点返回语义域，不重新匹配查询文本。"""
    anchor_set = {str(anchor).strip() for anchor in anchors if str(anchor).strip()}
    domains: list[str] = []
    for rule in SEMANTIC_RULES:
        if str(rule.get("anchor") or "").strip() in anchor_set:
            domains.extend(str(domain).strip() for domain in rule.get("domains", []) if str(domain).strip())
    return unique_terms(domains)


def canonical_semantic_token(value: object) -> str:
    """返回单个词项对应的规范语义锚点名称。"""
    token = re.sub(r"\s+", " ", str(value or "").strip().lower())
    if not token:
        return ""
    direct = _canonical_semantic_rule_token(token)
    if direct:
        return direct
    for suffix in ("化", "风格"):
        if token.endswith(suffix) and len(token) > len(suffix):
            stem = token[: -len(suffix)]
            direct = _canonical_semantic_rule_token(stem)
            return direct or stem
    return token


def _append_semantic_rule_signal(
    rule: dict[str, Any],
    *,
    concepts: list[str],
    expanded: list[str],
    aliases: list[str],
    anchors: list[str],
    domains: list[str],
) -> None:
    concepts.append(str(rule.get("name") or ""))
    expanded.extend(rule.get("terms", []))
    aliases.extend(rule.get("category_aliases", []))
    anchor = str(rule.get("anchor") or "").strip()
    if anchor:
        anchors.append(anchor)
    domains.extend(str(domain).strip() for domain in rule.get("domains", []) if str(domain).strip())


def _apply_compositional_semantic_inferences(
    lower_query: str,
    *,
    concepts: list[str],
    expanded: list[str],
    aliases: list[str],
    anchors: list[str],
    domains: list[str],
) -> None:
    anchor_set = {str(anchor).strip().lower() for anchor in anchors if str(anchor).strip()}
    for inference in COMPOSITIONAL_INFERENCES:
        if not _compositional_inference_matches(inference, lower_query, anchor_set):
            continue
        _append_named_semantic_rule(
            inference.anchor,
            concepts=concepts,
            expanded=expanded,
            aliases=aliases,
            anchors=anchors,
            domains=domains,
        )
        anchor_set.add(inference.anchor)


COMPOSITIONAL_INFERENCES: tuple[CompositionalInference, ...] = (
    CompositionalInference(
        anchor="roleplay",
        required_anchors=frozenset({"bimbo"}),
        signal=lambda text: _has_identity_progression_signal(text),
        any_anchor=frozenset({"gameplay", "framework"}),
    ),
    CompositionalInference(anchor="pregnancy", signal=lambda text: _has_reproductive_system_signal(text)),
    CompositionalInference(
        anchor="sexworker_style",
        required_anchors=frozenset({"outfit"}),
        signal=lambda text: _has_sexworker_style_signal(text),
    ),
    CompositionalInference(anchor="framework", signal=lambda text: _has_framework_signal(text)),
    CompositionalInference(anchor="loverslab", signal=lambda text: _has_loverslab_source_signal(text)),
)


def _compositional_inference_matches(
    inference: CompositionalInference,
    lower_query: str,
    anchor_set: set[str],
) -> bool:
    if inference.anchor in anchor_set or anchor_set & inference.blocked_anchors:
        return False
    if not inference.required_anchors.issubset(anchor_set):
        return False
    if inference.any_anchor and not anchor_set & inference.any_anchor and not inference.signal(lower_query):
        return False
    return inference.signal(lower_query) or bool(inference.any_anchor and anchor_set & inference.any_anchor)


def _append_named_semantic_rule(
    name: str,
    *,
    concepts: list[str],
    expanded: list[str],
    aliases: list[str],
    anchors: list[str],
    domains: list[str],
) -> None:
    for rule in SEMANTIC_RULES:
        if name in {
            str(rule.get("name") or "").strip().lower(),
            str(rule.get("anchor") or "").strip().lower(),
        }:
            _append_semantic_rule_signal(rule, concepts=concepts, expanded=expanded, aliases=aliases, anchors=anchors, domains=domains)
            return


def _has_identity_progression_signal(text: str) -> bool:
    return any(marker in text for marker in {"路线", "养成", "成长", "进展", "身份", "职业", "progression", "play as"})


def _has_reproductive_system_signal(text: str) -> bool:
    return any(marker in text for marker in {"生育", "受孕", "繁殖", "fertility", "breeding", "birth"})


def _has_sexworker_style_signal(text: str) -> bool:
    return any(marker in text for marker in {"风尘", "陪酒", "夜店", "stripper", "escort"})


def _has_framework_signal(text: str) -> bool:
    return any(marker in text for marker in {"框架", "基础框架", "核心系统", "framework", "mod framework"})


def _has_loverslab_source_signal(text: str) -> bool:
    return any(
        source == "loverslab" and _marker_matches_text(str(alias).lower(), text)
        for alias, source in SOURCE_ALIASES.items()
    )


def _canonical_semantic_rule_token(token: str) -> str:
    for rule in SEMANTIC_RULES:
        canonical = str(rule.get("anchor") or rule.get("name") or "").strip().lower()
        if not canonical:
            continue
        values = [
            rule.get("name"),
            rule.get("anchor"),
            *list(rule.get("markers", [])),
            *list(rule.get("terms", [])),
        ]
        if token in {str(value or "").strip().lower() for value in values if str(value or "").strip()}:
            return canonical
    return ""


def _marker_matches_text(marker: str, text: str) -> bool:
    if not marker or not text:
        return False
    if re.search(r"[\u4e00-\u9fff]", marker):
        return marker in text
    return re.search(rf"(?<![a-z0-9]){re.escape(marker)}(?![a-z0-9])", text) is not None


def unique_terms(values: list[str]) -> list[str]:
    return unique_text(re.sub(r"\s+", " ", str(value or "").strip().lower()) for value in values)
