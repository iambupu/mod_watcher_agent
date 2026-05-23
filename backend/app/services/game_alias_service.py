"""File-backed game alias learning for Agent game slot matching."""

import json
from pathlib import Path
from typing import Any

from app.config import settings


def alias_key(value: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    import re

    return re.sub(r"[\s_\-:：/\\()（）]+", "", value.strip().lower())


def alias_file_path(path: str | Path | None = None) -> Path:
    """处理当前模块的业务逻辑并返回结果。"""
    if path is not None:
        return Path(path)
    configured = Path(settings.GAME_ALIAS_FILE)
    if configured.is_absolute():
        return configured
    return Path(__file__).resolve().parents[2] / configured


def load_game_aliases(path: str | Path | None = None) -> dict[str, list[str]]:
    """加载配置或持久化数据。"""
    file_path = alias_file_path(path)
    if not file_path.exists():
        return {}
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw_aliases = data.get("aliases") if isinstance(data, dict) else data
    if not isinstance(raw_aliases, dict):
        return {}
    aliases: dict[str, list[str]] = {}
    for alias, targets in raw_aliases.items():
        alias_text = str(alias or "").strip()
        if not alias_text:
            continue
        if isinstance(targets, str):
            target_list = [targets]
        elif isinstance(targets, list):
            target_list = [str(item).strip() for item in targets if str(item or "").strip()]
        else:
            continue
        if target_list:
            aliases[alias_text] = list(dict.fromkeys(target_list))
    return aliases


def _write_game_aliases(aliases: dict[str, list[str]], path: str | Path | None = None) -> None:
    """内部辅助函数，用于拆分上层流程中的局部规则。"""
    file_path = alias_file_path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"aliases": dict(sorted(aliases.items(), key=lambda item: alias_key(item[0])))}
    tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(file_path)


def build_resolved_aliases(allowed_values: list[str], aliases: dict[str, list[str]] | None = None) -> dict[str, list[str]]:
    """构建后续流程需要的数据结构。"""
    raw_aliases = aliases if aliases is not None else load_game_aliases()
    allowed_by_key = {alias_key(value): value for value in allowed_values}
    resolved_aliases: dict[str, list[str]] = {}
    for alias, targets in raw_aliases.items():
        resolved = []
        for target in targets:
            value = allowed_by_key.get(alias_key(target))
            if value and value not in resolved:
                resolved.append(value)
        if resolved:
            resolved_aliases[alias_key(alias)] = resolved
    return resolved_aliases


def add_game_alias_mappings(
    mappings: Any,
    allowed_games: list[str],
    path: str | Path | None = None,
) -> dict[str, list[str]]:
    """Persist validated alias mappings discovered by the LLM.

    Accepted mapping shapes:
    - {"alias": "剑星", "game": "Stellar Blade"}
    - {"alias": "剑星", "target": "Stellar Blade"}
    - {"剑星": "Stellar Blade"}
    """
    if not mappings:
        return load_game_aliases(path)
    allowed_by_key = {alias_key(value): value for value in allowed_games}
    aliases = load_game_aliases(path)
    aliases_by_key = {alias_key(alias): alias for alias in aliases}

    normalized_items: list[tuple[str, str]] = []
    if isinstance(mappings, dict):
        for alias, target in mappings.items():
            normalized_items.append((str(alias or ""), str(target or "")))
    elif isinstance(mappings, list):
        for item in mappings:
            if isinstance(item, dict):
                alias = str(item.get("alias") or item.get("name") or "")
                target = str(item.get("game") or item.get("target") or item.get("canonical") or "")
                normalized_items.append((alias, target))

    changed = False
    for alias, target in normalized_items:
        alias_text = alias.strip()
        target_value = allowed_by_key.get(alias_key(target))
        if not alias_text or not target_value:
            continue
        if len(alias_text) > 80 or len(target_value) > 255:
            continue
        if alias_key(alias_text) == alias_key(target_value):
            continue
        existing_alias = aliases_by_key.get(alias_key(alias_text), alias_text)
        existing_targets = aliases.setdefault(existing_alias, [])
        if target_value not in existing_targets:
            existing_targets.append(target_value)
            changed = True
        aliases_by_key[alias_key(alias_text)] = existing_alias
    if changed:
        _write_game_aliases(aliases, path)
    return aliases
