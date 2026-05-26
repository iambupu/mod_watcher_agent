import re
from dataclasses import dataclass, field
from typing import Any

from app.services.agent.semantic_taxonomy import SEMANTIC_RULES


@dataclass
class SemanticSignals:
    expanded_terms: list[str] = field(default_factory=list)
    category_aliases: list[str] = field(default_factory=list)
    matched_concepts: list[str] = field(default_factory=list)
    anchors: list[str] = field(default_factory=list)
    domains: list[str] = field(default_factory=list)


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


def semantic_domains_for_anchors(anchors: list[str]) -> list[str]:
    """Return semantic domains for canonical anchors without rematching query text."""
    anchor_set = {str(anchor).strip() for anchor in anchors if str(anchor).strip()}
    domains: list[str] = []
    for rule in SEMANTIC_RULES:
        if str(rule.get("anchor") or "").strip() in anchor_set:
            domains.extend(str(domain).strip() for domain in rule.get("domains", []) if str(domain).strip())
    return unique_terms(domains)


def canonical_semantic_token(value: object) -> str:
    """Return the canonical semantic anchor/name for a single lexical token."""
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
    if "bimbo" in anchor_set and (
        {"gameplay", "framework"} & anchor_set or _has_identity_progression_signal(lower_query)
    ):
        _append_named_semantic_rule("roleplay", concepts=concepts, expanded=expanded, aliases=aliases, anchors=anchors, domains=domains)
    if "pregnancy" not in anchor_set and _has_reproductive_system_signal(lower_query):
        _append_named_semantic_rule("pregnancy", concepts=concepts, expanded=expanded, aliases=aliases, anchors=anchors, domains=domains)
    if "sexworker_style" not in anchor_set and "outfit" in anchor_set and _has_sexworker_style_signal(lower_query):
        _append_named_semantic_rule("sexworker_style", concepts=concepts, expanded=expanded, aliases=aliases, anchors=anchors, domains=domains)


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
        if str(rule.get("name") or "").strip() == name:
            _append_semantic_rule_signal(rule, concepts=concepts, expanded=expanded, aliases=aliases, anchors=anchors, domains=domains)
            return


def _has_identity_progression_signal(text: str) -> bool:
    return any(marker in text for marker in {"路线", "养成", "成长", "进展", "身份", "职业", "progression", "play as"})


def _has_reproductive_system_signal(text: str) -> bool:
    return any(marker in text for marker in {"生育", "受孕", "繁殖", "fertility", "breeding", "birth"})


def _has_sexworker_style_signal(text: str) -> bool:
    return any(marker in text for marker in {"风尘", "陪酒", "夜店", "stripper", "escort"})


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
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if token and token not in seen:
            merged.append(token)
            seen.add(token)
    return merged
