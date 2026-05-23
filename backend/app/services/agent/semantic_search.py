import re
from dataclasses import dataclass, field

SCOPE_MARKER = "[scope]"

STOP_WORDS = {
    "mod",
    "mods",
    "模组",
    "最近",
    "最新",
    "更新",
    "热门",
    "哪些",
    "有哪些",
    "有没有",
    "只看",
    "查看",
    "看看",
    "的",
    "和",
    "了",
}

CHINESE_QUERY_FILLERS = (
    "有什么",
    "有哪些",
    "有没有",
    "帮我找",
    "帮我看看",
    "我想找",
    "想找",
    "查找",
    "搜索",
    "和",
    "相关的",
    "相关",
    "类似的",
    "类似",
    "mod",
    "mods",
    "模组",
)

SEMANTIC_RULES: tuple[dict, ...] = (
    {
        "name": "female",
        "markers": ["女性", "女装", "女款", "女士", "女人", "妹子", "female", "woman", "women", "girl"],
        "terms": ["female", "women", "girl", "cbbe", "unp", "bodyslide", "eve"],
    },
    {
        "name": "male",
        "markers": ["男性", "男装", "男款", "男士", "男人", "male", "man", "men", "boy"],
        "terms": ["male", "men", "himbo", "sos", "male body"],
    },
    {
        "name": "outfit",
        "markers": ["服装", "衣服", "衣装", "套装", "外观", "裙", "内衣", "outfit", "clothing", "dress", "robe"],
        "terms": ["outfit", "clothing", "dress", "robe", "bikini", "lingerie", "costume", "suit"],
        "category_aliases": ["clothing", "accessories", "outfit", "outfits", "服装"],
    },
    {
        "name": "armor",
        "markers": ["护甲", "盔甲", "轻甲", "重甲", "甲", "armor", "armour", "light armor", "heavy armor"],
        "terms": ["armor", "armour", "light armor", "heavy armor", "clothing"],
        "category_aliases": ["armor", "armour", "轻甲", "护甲"],
    },
    {
        "name": "gameplay",
        "markers": ["玩法", "机制", "战斗", "生存", "任务", "平衡", "perk", "技能", "gameplay", "combat", "quest"],
        "terms": ["gameplay", "combat", "quest", "perk", "survival", "balance", "mechanics"],
        "category_aliases": ["gameplay", "combat", "quests", "skills", "perks", "游戏玩法"],
    },
    {
        "name": "visual",
        "markers": ["画质", "画面", "材质", "纹理", "光照", "美化", "视觉", "graphics", "texture", "visual", "lighting"],
        "terms": ["graphics", "texture", "textures", "visual", "lighting", "environment", "reshade"],
        "category_aliases": ["graphics", "textures", "visuals", "environment", "models", "美化"],
    },
    {
        "name": "follower",
        "markers": ["随从", "同伴", "伙伴", "follower", "companion"],
        "terms": ["follower", "companion", "npc"],
        "category_aliases": ["followers", "companions", "npcs", "随从"],
    },
    {
        "name": "animation",
        "markers": ["动画", "动作", "姿势", "animation", "pose", "moveset"],
        "terms": ["animation", "animations", "pose", "moveset", "behavior"],
        "category_aliases": ["animation", "animations", "poses"],
    },
    {
        "name": "utility",
        "markers": ["工具", "框架", "修复", "补丁", "性能", "utility", "framework", "fix", "patch", "performance"],
        "terms": ["utility", "framework", "fix", "patch", "performance", "bugfix"],
        "category_aliases": ["utilities", "bug fixes", "patches", "modders resources"],
    },
    {
        "name": "cosmetic_face",
        "markers": ["玻尿酸", "肉毒", "botox", "botoxed", "hyaluronic"],
        "terms": ["玻尿酸", "botox", "botoxed", "hyaluronic"],
    },
)


@dataclass
class SemanticQuery:
    raw_query: str
    clean_query: str
    base_keywords: list[str] = field(default_factory=list)
    expanded_terms: list[str] = field(default_factory=list)
    category_aliases: list[str] = field(default_factory=list)

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


def strip_scope(query: str) -> str:
    """处理当前模块的业务逻辑并返回结果。"""
    return query.split(SCOPE_MARKER, 1)[0].strip()


def semantic_query(query: str, categories: list[str] | None = None) -> SemanticQuery:
    """处理当前模块的业务逻辑并返回结果。"""
    clean_query = strip_scope(query)
    lower_query = clean_query.lower()
    category_text = " ".join(categories or []).lower()
    expanded: list[str] = []
    aliases: list[str] = []
    for rule in SEMANTIC_RULES:
        markers = [str(marker).lower() for marker in rule.get("markers", [])]
        if any(marker in lower_query or marker in category_text for marker in markers):
            expanded.extend(rule.get("terms", []))
            aliases.extend(rule.get("category_aliases", []))
    return SemanticQuery(
        raw_query=query,
        clean_query=clean_query,
        base_keywords=base_keywords(clean_query),
        expanded_terms=unique_terms(expanded),
        category_aliases=unique_terms(aliases),
    )


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


def infer_categories(query: str, available_categories: list[str], existing: list[str] | None = None) -> list[str]:
    """处理当前模块的业务逻辑并返回结果。"""
    selected = list(existing or [])
    semantic = semantic_query(query, selected)
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
    merged: list[str] = []
    seen: set[str] = set()
    for value in values:
        token = re.sub(r"\s+", " ", str(value or "").strip().lower())
        if token and token not in seen:
            merged.append(token)
            seen.add(token)
    return merged
