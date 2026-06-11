# 中文注释：封装后端服务层的来源身份归一化和匹配逻辑。

import hashlib
import re
from urllib.parse import urlparse

from sqlalchemy import or_
from sqlmodel import Session, select

from app.models.mod import Mod
from app.services.loverslab.url_utils import extract_loverslab_file_id_from_url

GENERIC_LOVERSLAB_GAME_LABELS = {"", "loverslab", "nexusmods", "nexus mods"}


def canonical_external_id(
    source: str,
    external_id: str,
    url: str = "",
    *,
    game: str | None = None,
    game_domain: str | None = None,
) -> str:
    """Return the source ID format used by adapters and database dedupe."""
    normalized_source = source.strip().lower()
    parsed = urlparse(url.strip())
    path = parsed.path or ""
    if normalized_source == "nexusmods":
        matched = _nexusmods_url_match(path)
        if matched:
            return _nexusmods_identity(matched.group("domain"), matched.group("mod_id"))
        parsed_id = _parse_nexusmods_identity(external_id)
        if parsed_id is not None:
            return _nexusmods_identity(parsed_id[0], parsed_id[1])
    if normalized_source == "loverslab":
        scope = _loverslab_identity_scope(game=game, game_domain=game_domain)
        parsed_id = _parse_loverslab_identity(external_id)
        url_file_id = extract_loverslab_file_id_from_url(path)
        file_id = url_file_id or (parsed_id[1] if parsed_id is not None else external_id.strip())
        if scope and file_id:
            return f"{scope}:{file_id}"
        if parsed_id is not None:
            return f"{parsed_id[0]}:{file_id}"
        if url_file_id:
            return file_id
    return external_id.strip()


def external_id_aliases(
    source: str,
    external_id: str,
    url: str = "",
    *,
    game: str | None = None,
    game_domain: str | None = None,
) -> list[str]:
    """Return current and legacy IDs that may identify the same source page."""
    canonical = canonical_external_id(source, external_id, url, game=game, game_domain=game_domain)
    aliases = [canonical, external_id.strip()]
    if source.strip().lower() == "nexusmods":
        parsed_id = _parse_nexusmods_identity(canonical)
        if parsed_id is not None:
            aliases.append(parsed_id[1])
    normalized_url = url.strip()
    if source.strip().lower() == "loverslab":
        parsed_id = _parse_loverslab_identity(canonical)
        if parsed_id is not None:
            aliases.append(parsed_id[1])
        file_id = extract_loverslab_file_id_from_url(urlparse(normalized_url).path or "")
        if file_id:
            aliases.append(file_id)
        if normalized_url:
            aliases.append(hashlib.sha256(normalized_url.encode("utf-8")).hexdigest()[:32])
            aliases.append(hashlib.sha256(_canonicalize_loverslab_url(normalized_url).encode("utf-8")).hexdigest()[:16])
    return list(dict.fromkeys(alias for alias in aliases if alias))


def find_existing_mod_by_identity(
    session: Session,
    source: str,
    external_id: str,
    url: str = "",
    *,
    game: str | None = None,
    game_domain: str | None = None,
) -> Mod | None:
    """Find a mod by canonical ID, legacy aliases, or exact URL.

    The canonical row is preferred so legacy alias rows are not rewritten into
    an already-existing unique key.
    """
    normalized_source = source.strip().lower()
    canonical = canonical_external_id(normalized_source, external_id, url, game=game, game_domain=game_domain)
    if normalized_source == "nexusmods":
        return _find_existing_nexusmods_mod(session, canonical, url)
    if normalized_source == "loverslab":
        return _find_existing_loverslab_mod(
            session,
            canonical,
            external_id,
            url,
            game=game,
            game_domain=game_domain,
        )

    existing = session.exec(
        select(Mod).where(
            Mod.source == normalized_source,
            Mod.external_id == canonical,
        )
    ).first()
    if existing is not None:
        return existing

    aliases = external_id_aliases(normalized_source, canonical, url)
    conditions = [Mod.external_id.in_(aliases)]
    normalized_url = url.strip()
    if normalized_url:
        conditions.append(Mod.url == normalized_url)
    return session.exec(
        select(Mod).where(
            Mod.source == normalized_source,
            or_(*conditions),
        )
    ).first()


def _canonicalize_loverslab_url(url: str) -> str:
    canonical = url.lower().strip()
    for prefix in ("https://", "http://"):
        if canonical.startswith(prefix):
            canonical = canonical[len(prefix):]
            break
    return canonical.rstrip("/")


def _nexusmods_url_match(path: str):
    return re.search(
        r"^/(?P<domain>[^/]+)/mods/(?P<mod_id>\d+)(?:/|$)",
        path,
        flags=re.IGNORECASE,
    )


def _nexusmods_identity(domain: str, mod_id: str) -> str:
    return f"{domain.strip().lower()}:{mod_id.strip()}"


def _parse_nexusmods_identity(external_id: str) -> tuple[str, str] | None:
    value = external_id.strip()
    matched = re.fullmatch(r"([a-z0-9_-]+):(\d+)", value, flags=re.IGNORECASE)
    if not matched:
        return None
    return matched.group(1), matched.group(2)


def _parse_loverslab_identity(external_id: str) -> tuple[str, str] | None:
    value = external_id.strip()
    matched = re.fullmatch(r"([a-z0-9][a-z0-9_-]*):(\d+)", value, flags=re.IGNORECASE)
    if not matched:
        return None
    return matched.group(1).lower(), matched.group(2)


def _loverslab_game_scope(value: str | None) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in GENERIC_LOVERSLAB_GAME_LABELS:
        return None
    scope = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return scope or None


def _loverslab_identity_scope(*, game: str | None, game_domain: str | None) -> str | None:
    return _loverslab_game_scope(game_domain) or _loverslab_game_scope(game)


def _find_existing_nexusmods_mod(
    session: Session,
    canonical: str,
    url: str,
) -> Mod | None:
    existing = session.exec(
        select(Mod).where(
            Mod.source == "nexusmods",
            Mod.external_id == canonical,
        )
    ).first()
    if existing is not None:
        return existing

    normalized_url = url.strip()
    if normalized_url:
        existing = session.exec(
            select(Mod).where(
                Mod.source == "nexusmods",
                Mod.url == normalized_url,
            )
        ).first()
        if existing is not None:
            return existing

    identity = _parse_nexusmods_identity(canonical)
    if identity is None:
        return session.exec(
            select(Mod).where(
                Mod.source == "nexusmods",
                Mod.external_id == canonical,
            )
        ).first()

    domain, mod_id = identity
    legacy_conditions = [Mod.game_domain == domain]
    if normalized_url:
        legacy_conditions.append(Mod.url == normalized_url)
    legacy_conditions.append(Mod.url.ilike(f"%/{domain}/mods/{mod_id}%"))
    return session.exec(
        select(Mod).where(
            Mod.source == "nexusmods",
            Mod.external_id == mod_id,
            or_(*legacy_conditions),
        )
    ).first()


def _find_existing_loverslab_mod(
    session: Session,
    canonical: str,
    external_id: str,
    url: str,
    *,
    game: str | None,
    game_domain: str | None,
) -> Mod | None:
    existing = session.exec(
        select(Mod).where(
            Mod.source == "loverslab",
            Mod.external_id == canonical,
        )
    ).first()
    if existing is not None:
        return existing

    normalized_url = url.strip()
    if normalized_url:
        existing = session.exec(
            select(Mod).where(
                Mod.source == "loverslab",
                Mod.url == normalized_url,
            )
        ).first()
        if existing is not None:
            return existing

    aliases = external_id_aliases("loverslab", external_id, url, game=game, game_domain=game_domain)
    scope = _loverslab_identity_scope(game=game, game_domain=game_domain)
    if scope:
        game_conditions = [
            Mod.game_domain == scope,
            Mod.game == (game or ""),
            Mod.game.in_(list(GENERIC_LOVERSLAB_GAME_LABELS)),
        ]
    else:
        game_conditions = [
            Mod.game_domain.is_(None),
            Mod.game.in_(list(GENERIC_LOVERSLAB_GAME_LABELS)),
        ]
    return session.exec(
        select(Mod).where(
            Mod.source == "loverslab",
            Mod.external_id.in_(aliases),
            or_(*game_conditions),
        )
    ).first()
