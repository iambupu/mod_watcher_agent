from app.services.agent.schemas import AgentChatResponse


def build_memory_evidence(memory_context: object, *, evidence_id: str = "") -> list[dict[str, object]]:
    if not isinstance(memory_context, dict):
        return []
    short_term = memory_context.get("short_term") if isinstance(memory_context.get("short_term"), dict) else {}
    long_term = memory_context.get("long_term") if isinstance(memory_context.get("long_term"), dict) else {}
    merged = memory_context.get("merged") if isinstance(memory_context.get("merged"), dict) else {}
    evidence: list[dict[str, object]] = []
    _append_memory_slot_evidence(
        evidence,
        source="short_term_memory",
        prefix="m_short_last_query",
        slots=short_term.get("last_query_context"),
        evidence_id=evidence_id,
    )
    _append_memory_slot_evidence(
        evidence,
        source="short_term_memory",
        prefix="m_short_constraints",
        slots=short_term.get("active_constraints"),
        evidence_id=evidence_id,
    )
    favorite_summary = long_term.get("favorite_summary") if isinstance(long_term.get("favorite_summary"), dict) else {}
    if favorite_summary:
        for field, value in [
            ("game", _first_list_value(favorite_summary.get("top_games"))),
            ("source", _first_list_value(favorite_summary.get("top_sources"))),
            ("category", _first_list_value(favorite_summary.get("top_categories"))),
            ("adult_content_allowed", favorite_summary.get("adult_content_allowed")),
        ]:
            if value in (None, "", []):
                continue
            evidence.append(
                {
                    "fragment_id": f"m_long_favorite_{field}",
                    "source": "long_term_favorite",
                    "field": field,
                    "value": value,
                    "evidence_id": evidence_id,
                }
            )
    conversation_summary = (
        long_term.get("conversation_summary") if isinstance(long_term.get("conversation_summary"), dict) else {}
    )
    if conversation_summary:
        for field, value in [
            ("game", _first_list_value(conversation_summary.get("top_games"))),
            ("source", _first_list_value(conversation_summary.get("top_sources"))),
            ("category", _first_list_value(conversation_summary.get("top_categories"))),
            ("adult_content_preference", conversation_summary.get("adult_content_preference")),
        ]:
            if value in (None, "", []):
                continue
            evidence.append(
                {
                    "fragment_id": f"m_long_conversation_{field}",
                    "source": "long_term_conversation",
                    "field": field,
                    "value": value,
                    "evidence_id": evidence_id,
                }
            )
    memory_meta = merged.get("memory_meta") if isinstance(merged.get("memory_meta"), dict) else {}
    if memory_meta:
        if memory_meta.get("preference_stale") is not None:
            evidence.append(
                {
                    "fragment_id": "m_long_meta_preference_stale",
                    "source": "long_term_meta",
                    "field": "preference_stale",
                    "value": bool(memory_meta.get("preference_stale")),
                    "evidence_id": evidence_id,
                }
            )
        if memory_meta.get("preferences_age_days") is not None:
            evidence.append(
                {
                    "fragment_id": "m_long_meta_preferences_age_days",
                    "source": "long_term_meta",
                    "field": "preferences_age_days",
                    "value": int(memory_meta.get("preferences_age_days") or 0),
                    "evidence_id": evidence_id,
                }
            )
        updated_at = memory_meta.get("preferences_updated_at")
        if updated_at:
            evidence.append(
                {
                    "fragment_id": "m_long_meta_preferences_updated_at",
                    "source": "long_term_meta",
                    "field": "preferences_updated_at",
                    "value": str(updated_at),
                    "evidence_id": evidence_id,
                }
            )
    return evidence


def build_memory_writeback_evidence(writeback: object) -> list[dict[str, object]]:
    if not isinstance(writeback, dict) or writeback.get("status") != "succeeded":
        return []
    context = writeback.get("context") if isinstance(writeback.get("context"), dict) else {}
    evidence_id = str(writeback.get("evidence_id") or "").strip()
    evidence: list[dict[str, object]] = []
    for field, value in context.items():
        if field in {"query", "source"} or value in (None, "", []):
            continue
        evidence.append(
            {
                "fragment_id": f"m_writeback_{field}",
                "source": "memory_writeback",
                "field": field,
                "value": value,
                "evidence_id": evidence_id,
            }
        )
    return evidence


def link_understanding_to_evidence(response: AgentChatResponse) -> None:
    understanding = response.understanding if isinstance(response.understanding, dict) else None
    memory = response.memory_evidence if isinstance(response.memory_evidence, list) else []
    retrieval = response.retrieval_evidence if isinstance(response.retrieval_evidence, list) else []
    if not understanding:
        return
    source_fragments: dict[str, list[str]] = {}
    source_field_fragments: dict[tuple[str, str], list[str]] = {}
    memory_field_fragments: dict[str, list[str]] = {}
    for item in memory:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        field = str(item.get("field") or "").strip()
        fragment_id = str(item.get("fragment_id") or "").strip()
        if source and fragment_id:
            source_fragments.setdefault(source, []).append(fragment_id)
        if source and field and fragment_id:
            source_field_fragments.setdefault((source, field), []).append(fragment_id)
            memory_field_fragments.setdefault(field, []).append(fragment_id)
    field_fragments: dict[str, list[str]] = {}
    for item in retrieval:
        if not isinstance(item, dict):
            continue
        fragment_id = str(item.get("fragment_id") or "").strip()
        fields = item.get("fields")
        if not fragment_id or not isinstance(fields, list):
            continue
        for field in fields:
            key = str(field or "").strip()
            if key:
                field_fragments.setdefault(key, []).append(fragment_id)
    field_aliases = {
        "game": ["game", "games", "game_domains"],
        "source": ["source", "sources"],
        "category": ["category", "categories"],
        "adult_content": ["adult_content"],
        "sort_field": ["sort_field"],
        "sort_order": ["sort_order"],
        "semantic_anchors": ["semantic_anchors", "semantic_anchor"],
        "semantic_domains": ["semantic_domains", "semantic_domain"],
    }
    evidence_items = understanding.get("evidence")
    if not isinstance(evidence_items, list):
        return
    conflict_fragments = build_memory_conflict_evidence(understanding, memory)
    if conflict_fragments:
        memory.extend(conflict_fragments)
        response.memory_evidence = memory
        for conflict in conflict_fragments:
            source = str(conflict.get("source") or "").strip()
            field = str(conflict.get("field") or "").strip()
            fragment_id = str(conflict.get("fragment_id") or "").strip()
            if source and fragment_id:
                source_fragments.setdefault(source, []).append(fragment_id)
            if source and field and fragment_id:
                source_field_fragments.setdefault((source, field), []).append(fragment_id)
    conflict_field_fragments: dict[str, list[str]] = {}
    for item in memory:
        if not isinstance(item, dict):
            continue
        if str(item.get("source") or "") != "memory_conflict":
            continue
        field = str(item.get("field") or "").strip()
        fragment_id = str(item.get("fragment_id") or "").strip()
        if field and fragment_id:
            conflict_field_fragments.setdefault(field, []).append(fragment_id)
    for item in evidence_items:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        source = str(item.get("source") or "").strip()
        related_fragments: list[str] = []
        related_fragments.extend(source_field_fragments.get((source, field), []))
        if not related_fragments:
            related_fragments.extend(source_fragments.get(source, []))
        for alias in field_aliases.get(field, [field]):
            related_fragments.extend(field_fragments.get(alias, []))
        if field in {"semantic_anchors", "semantic_domains"}:
            for alias in field_aliases.get(field, [field]):
                related_fragments.extend(memory_field_fragments.get(alias, []))
        related_fragments.extend(conflict_field_fragments.get(field, []))
        if related_fragments:
            item["related_fragments"] = sorted(set(related_fragments))


def build_memory_conflict_evidence(
    understanding: dict[str, object],
    memory_evidence: list[dict[str, object]],
) -> list[dict[str, object]]:
    slots = understanding.get("slots") if isinstance(understanding.get("slots"), dict) else {}
    if not slots:
        return []
    memory_by_field: dict[str, list[tuple[str, object]]] = {}
    evidence_id = _memory_evidence_id(memory_evidence)
    preference_stale = any(
        isinstance(item, dict)
        and str(item.get("field") or "").strip() == "preference_stale"
        and bool(item.get("value"))
        for item in memory_evidence
    )
    for item in memory_evidence:
        if not isinstance(item, dict):
            continue
        field = str(item.get("field") or "").strip()
        source = str(item.get("source") or "").strip()
        if not field or not source:
            continue
        if preference_stale and source == "long_term_favorite":
            continue
        memory_by_field.setdefault(field, []).append((source, item.get("value")))
    conflicts: list[dict[str, object]] = []
    for field, slot_value in slots.items():
        for source, memory_value in memory_by_field.get(str(field), []):
            if _same_value(slot_value, memory_value):
                continue
            severity = _conflict_severity(str(field))
            conflicts.append(
                {
                    "fragment_id": f"m_conflict_{severity}_{source}_{field}",
                    "source": "memory_conflict",
                    "field": str(field),
                    "severity": severity,
                    "evidence_id": evidence_id,
                    "value": {
                        "understanding": slot_value,
                        "memory_source": source,
                        "memory": memory_value,
                    },
                }
            )
    unique: dict[str, dict[str, object]] = {}
    for item in conflicts:
        unique[str(item["fragment_id"])] = item
    return list(unique.values())


def _append_memory_slot_evidence(
    target: list[dict[str, object]],
    *,
    source: str,
    prefix: str,
    slots: object,
    evidence_id: str = "",
) -> None:
    if not isinstance(slots, dict):
        return
    for field, value in slots.items():
        normalized_field = _normalize_memory_field(field)
        if value in (None, "", []):
            continue
        target.append(
            {
                "fragment_id": f"{prefix}_{normalized_field}",
                "source": source,
                "field": normalized_field,
                "value": value,
                "evidence_id": evidence_id,
            }
        )


def _memory_evidence_id(memory_evidence: list[dict[str, object]]) -> str:
    for item in memory_evidence:
        if not isinstance(item, dict):
            continue
        evidence_id = str(item.get("evidence_id") or "").strip()
        if evidence_id:
            return evidence_id
    return ""


def _normalize_memory_field(field: object) -> str:
    key = str(field or "").strip()
    aliases = {
        "source_name": "source",
        "sources": "source",
        "games": "game",
        "categories": "category",
        "semantic_anchor": "semantic_anchors",
        "semantic_domain": "semantic_domains",
    }
    return aliases.get(key, key)


def _first_list_value(value: object) -> object:
    if isinstance(value, list) and value:
        return value[0]
    return value


def _same_value(left: object, right: object) -> bool:
    if isinstance(left, str) or isinstance(right, str):
        return str(left or "").strip().lower() == str(right or "").strip().lower()
    return left == right


def _conflict_severity(field: str) -> str:
    hard_fields = {"game", "source", "category", "adult_content"}
    return "hard_conflict" if field in hard_fields else "soft_conflict"
