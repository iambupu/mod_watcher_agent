import re
from dataclasses import dataclass

from app.services.agent.semantic_search import base_keywords, canonical_semantic_token

_GENERIC_TERMS = {
    "mod",
    "mods",
    "模组",
    "风格",
    "style",
    "效果",
    "相关",
    "相关结果",
    "类似",
    "类似结果",
    "同类",
    "同类结果",
    "继续",
    "结果",
    "的结果",
    "related",
    "similar",
    "same",
    "continue",
    "more",
    "another",
    "result",
    "results",
    "ll",
    "loverslab",
    "nexus",
    "nexusmods",
    "这种",
    "那种",
    "方向",
    "direction",
}


@dataclass(frozen=True)
class FollowupDecision:
    is_followup: bool
    score: float
    low_signal: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class ContextInheritDecision:
    inherit_keywords: bool
    followup_score: float
    continuity_score: float
    inherit_score: float
    inherit_threshold: float
    topic_shift: bool
    low_signal: bool
    reasons: tuple[str, ...]
    policy_reasons: tuple[str, ...]


def is_contextual_followup(text: str) -> bool:
    return followup_decision(text).is_followup


def followup_decision(text: str) -> FollowupDecision:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return FollowupDecision(is_followup=False, score=0.0, low_signal=True, reasons=("empty_query",))
    terms = _clean_terms(base_keywords(lowered))
    lexical_terms = [term for term in terms if _is_lexical_token(term)]
    low_signal = (not _has_distinctive_terms(lexical_terms)) or _is_underspecified_followup_phrase(lowered, lexical_terms)
    score = 0.0
    reasons: list[str] = []
    if _has_reference_pronoun(lowered):
        score += 0.5
        reasons.append("has_reference")
    if _has_relational_intent(lowered):
        score += 0.2
        reasons.append("has_relational_intent")
    if low_signal:
        score += 0.24
        reasons.append("low_signal_query")
    density = _information_density(lexical_terms)
    if density < 0.45:
        score += 0.12
        reasons.append("low_information_density")
    if density >= 0.75 and _has_distinctive_terms(lexical_terms):
        score -= 0.15
        reasons.append("high_information_density")
    if len(lexical_terms) <= 2:
        score += 0.08
        reasons.append("short_lexical_query")
    if low_signal and len(lexical_terms) <= 2:
        score += 0.16
        reasons.append("underspecified_short_query")
    if len(lexical_terms) >= 4 and _has_distinctive_terms(lexical_terms):
        score -= 0.1
        reasons.append("rich_distinctive_query")
    normalized = min(score, 1.0)
    followup_threshold = 0.55
    if low_signal and len(lexical_terms) <= 2:
        followup_threshold = 0.44
    return FollowupDecision(
        is_followup=normalized >= followup_threshold,
        score=round(normalized, 3),
        low_signal=low_signal,
        reasons=tuple(reasons),
    )


def should_inherit_context_keywords(
    current_text: str,
    current_keywords: list[str] | None,
    context_keywords: list[str] | None,
) -> bool:
    context_terms = _clean_terms(context_keywords or [])
    if not context_terms:
        return False
    current_terms = _clean_terms(current_keywords or base_keywords(current_text))
    decision = followup_decision(current_text)
    continuity = semantic_continuity_score(current_text, current_terms, context_terms)
    if not current_terms:
        return continuity >= 0.52 or decision.low_signal
    lexical_terms = [term for term in current_terms if _is_lexical_token(term)]
    if not lexical_terms:
        return continuity >= 0.52 or decision.low_signal
    inherit_score = context_keyword_inherit_score(
        current_text=current_text,
        current_keywords=lexical_terms,
        context_keywords=context_terms,
    )
    # Strong current lexical signal should suppress stale context takeover.
    if _has_distinctive_terms(lexical_terms) and _information_density(lexical_terms) >= 0.6 and continuity < 0.4:
        return False
    return inherit_score >= 0.54


def context_keyword_inherit_score(
    current_text: str,
    current_keywords: list[str] | None,
    context_keywords: list[str] | None,
) -> float:
    context_terms = _clean_terms(context_keywords or [])
    if not context_terms:
        return 0.0
    current_terms = _clean_terms(current_keywords or base_keywords(current_text))
    decision = followup_decision(current_text)
    continuity = semantic_continuity_score(current_text, current_terms, context_terms)
    lexical_terms = [term for term in current_terms if _is_lexical_token(term)]
    if not lexical_terms:
        return max(decision.score, continuity)
    context_tokens = _informative_tokens(context_terms)
    current_tokens = _informative_tokens(lexical_terms)
    overlap_tokens = current_tokens & context_tokens
    topic_novelty = _topic_novelty_score(current_tokens, context_tokens)
    distinctive_current = _has_distinctive_terms(lexical_terms)
    has_followup_cue = any(reason in decision.reasons for reason in ("has_reference", "has_relational_intent"))
    hard_topic_shift = distinctive_current and continuity < 0.22 and topic_novelty >= 0.8 and not decision.low_signal
    if hard_topic_shift:
        return 0.0
    score = 0.0
    score += decision.score * 0.45
    score += continuity * 0.45
    if decision.low_signal:
        score += 0.2
    if has_followup_cue:
        score += 0.1
    if distinctive_current:
        novelty_penalty = 0.5
        if has_followup_cue and overlap_tokens:
            novelty_penalty = 0.28
        score -= topic_novelty * novelty_penalty
    if has_followup_cue and continuity >= 0.35 and overlap_tokens:
        score += 0.12
    if not distinctive_current and _information_density(lexical_terms) < 0.4:
        score += 0.08
    return round(max(0.0, min(score, 1.0)), 3)


def decide_context_inheritance(
    *,
    query: str,
    current_keywords: list[str] | None,
    context_keywords: list[str] | None,
    context_quality: float,
    has_refinement_constraints: bool,
    context_has_semantic_anchors: bool,
) -> ContextInheritDecision:
    effective_context_keywords = _clean_terms(context_keywords or [])
    decision = followup_decision(query)
    continuity = semantic_continuity_score(query, current_keywords or [], effective_context_keywords)
    inherit_score = context_keyword_inherit_score(query, current_keywords or [], effective_context_keywords)
    current_terms = _clean_terms(current_keywords or [])
    lexical_terms = [term for term in current_terms if _is_lexical_token(term)]
    distinctive_current = _has_distinctive_terms(lexical_terms)
    topic_shift = distinctive_current and continuity < 0.22 and inherit_score < 0.2

    threshold = 0.54
    policy_reasons: list[str] = []
    if decision.low_signal:
        threshold -= 0.06
        policy_reasons.append("low_signal_relax")
    if context_quality >= 0.45:
        threshold -= 0.04
        policy_reasons.append("high_context_quality_relax")
    if distinctive_current and continuity < 0.25:
        threshold += 0.08
        policy_reasons.append("low_continuity_tighten")
    threshold = max(0.38, min(threshold, 0.75))

    semantic_anchor_bias = bool(context_has_semantic_anchors) and (
        decision.low_signal or inherit_score >= 0.32
    )
    if semantic_anchor_bias:
        policy_reasons.append("semantic_anchor_bias")
    refinement_bias = (
        (not distinctive_current)
        and has_refinement_constraints
        and decision.low_signal
        and context_quality >= 0.2
    )
    if refinement_bias:
        policy_reasons.append("refinement_bias")

    inherit_keywords = bool(effective_context_keywords) and (
        inherit_score >= threshold or semantic_anchor_bias or refinement_bias
    )
    return ContextInheritDecision(
        inherit_keywords=bool(inherit_keywords),
        followup_score=round(float(decision.score), 3),
        continuity_score=round(float(continuity), 3),
        inherit_score=round(float(inherit_score), 3),
        inherit_threshold=round(float(threshold), 3),
        topic_shift=bool(topic_shift),
        low_signal=bool(decision.low_signal),
        reasons=tuple(decision.reasons),
        policy_reasons=tuple(policy_reasons),
    )


def semantic_continuity_score(
    current_text: str,
    current_keywords: list[str] | None,
    context_keywords: list[str] | None,
) -> float:
    current_terms = _clean_terms(current_keywords or base_keywords(current_text))
    context_terms = _clean_terms(context_keywords or [])
    if not current_terms or not context_terms:
        return 0.0
    current_tokens = _informative_tokens(current_terms)
    context_tokens = _informative_tokens(context_terms)
    if not current_tokens or not context_tokens:
        return 0.0
    overlap = current_tokens & context_tokens
    base = len(overlap) / max(len(current_tokens), len(context_tokens))
    exact_term_overlap = set(current_terms) & set(context_terms)
    if exact_term_overlap:
        base += 0.2
    return round(min(base, 1.0), 3)


def has_distinctive_keywords(keywords: list[str] | None) -> bool:
    terms = _clean_terms(keywords or [])
    lexical_terms = [term for term in terms if _is_lexical_token(term)]
    if not lexical_terms:
        return False
    return _has_distinctive_terms(lexical_terms)


def _has_reference_pronoun(text: str) -> bool:
    if any(marker in text for marker in ["这个", "它", "该"]):
        return True
    return re.search(r"\b(this|it|that)\b", text) is not None


def _has_relational_intent(text: str) -> bool:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return False
    if any(marker in compact for marker in ("类似", "同类", "相关结果", "类似结果", "同类结果")):
        return True
    patterns = (
        r"(?:^|[\s，。,？！!?.])(?:more|another|same|similar|related)(?:$|[\s，。,？！!?.])",
        r"(?:^|[\s，。,？！!?.]).{0,2}(?:继续|再来|还有|同类|类似|相关)(?:$|[\s，。,？！!?.])",
        r"(?:继续|保持).{0,4}(?:方向|这个方向|这个路子)",
        r"(?:^|[\s，。,？！!?.])(?:这种|那种|这个|那个)(?:$|[\s，。,？！!?.])",
    )
    return any(re.search(pattern, compact, flags=re.IGNORECASE) for pattern in patterns)


def _is_underspecified_followup_phrase(text: str, lexical_terms: list[str]) -> bool:
    if len(lexical_terms) > 1:
        return False
    # A single relational phrase (e.g. "这种风格继续找") rarely carries
    # enough standalone topic signal and should prefer context carry-over.
    return _has_relational_intent(text)


def _clean_terms(values: list[str]) -> list[str]:
    terms: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = re.sub(r"\s+", " ", str(value or "").strip().lower())
        token = _normalize_semantic_token(token)
        if token and token not in seen:
            terms.append(token)
            seen.add(token)
    return terms


def _has_distinctive_terms(terms: list[str]) -> bool:
    for term in terms:
        if _is_generic_term(term):
            continue
        if re.search(r"[\u4e00-\u9fff]", term) and len(term) >= 2:
            return True
        if re.fullmatch(r"[a-z0-9][a-z0-9_-]*", term) and len(term) >= 3:
            return True
    return False


def _information_density(terms: list[str]) -> float:
    if not terms:
        return 0.0
    informative = sum(1 for term in terms if not _is_generic_term(term))
    return informative / len(terms)


def _is_lexical_token(term: str) -> bool:
    return re.fullmatch(r"[a-z0-9\u4e00-\u9fff_-]+", term) is not None


def _informative_tokens(terms: list[str]) -> set[str]:
    tokens: set[str] = set()
    for term in terms:
        if _is_generic_term(term):
            continue
        parts = re.split(r"[_\-\s]+", term)
        for part in parts:
            token = _normalize_semantic_token(part.strip())
            if not token or _is_generic_term(token):
                continue
            if _is_lexical_token(token):
                tokens.add(token)
    return tokens


def _topic_novelty_score(current_tokens: set[str], context_tokens: set[str]) -> float:
    if not current_tokens:
        return 0.0
    if not context_tokens:
        return 1.0
    overlap = current_tokens & context_tokens
    novelty = 1.0 - (len(overlap) / len(current_tokens))
    return round(max(0.0, min(novelty, 1.0)), 3)


def _normalize_semantic_token(token: str) -> str:
    return canonical_semantic_token(token)


def _is_generic_term(term: str) -> bool:
    token = str(term or "").strip().lower()
    if not token or "\ufffd" in token or "�" in token:
        return True
    if re.fullmatch(r"的?(?:结果|风格)", token):
        return True
    return token in _GENERIC_TERMS
