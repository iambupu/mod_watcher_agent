from app.services.agent.planning.query_plan_hygiene import (
    looks_like_category_value,
    sanitize_category_slot_options,
    sanitize_query_plan_fields,
)


def test_sanitize_category_slot_options_keeps_known_categories_and_drops_titles():
    dirty_title = (
        "LamaKreis's Maidens of Skyrim - Serana Replacer and Lysanne Follower "
        "(High Poly) CBBE - CBBE 3BBB (3BA) - UBE and BHUNP compatible (Part 8)"
    )

    assert sanitize_category_slot_options(
        [
            "Clothing and Accessories",
            "Outfits",
            "Body, Face, and Hair",
            dirty_title,
            "Wear Armor over Devious Suits",
        ]
    ) == ["Clothing and Accessories", "Outfits", "Body, Face, and Hair"]


def test_category_shape_classifier_is_not_case_sensitive():
    assert looks_like_category_value("Clothing and Accessories") is True
    assert looks_like_category_value("Weapons") is True
    assert looks_like_category_value("Wear Armor over Devious Suits") is False


def test_sanitize_category_slot_options_normalizes_and_deduplicates_values():
    assert sanitize_category_slot_options([" Clothing ", "Clothing", None, "Outfits"]) == ["Clothing", "Outfits"]


def test_category_shape_classifier_keeps_unknown_but_well_formed_categories():
    assert sanitize_category_slot_options(
        [
            "Crafting",
            "Maps",
            "Children",
            "User Interface",
            "Cities, Towns, Villages, and Hamlets",
        ]
    ) == [
        "Crafting",
        "Maps",
        "Children",
        "User Interface",
        "Cities, Towns, Villages, and Hamlets",
    ]


def test_category_shape_classifier_drops_title_subtitle_shaped_categories():
    assert looks_like_category_value("Bimbos of Skyrim - BimboLips") is False
    assert sanitize_category_slot_options(
        ["Body", "Bimbos of Skyrim - BimboLips", "Character Presets"]
    ) == ["Body", "Character Presets"]


def test_category_shape_classifier_keeps_taxonomy_dash_categories():
    assert sanitize_category_slot_options(
        [
            "UI - HUD",
            "Gameplay - Immersion",
            "Modders Resources - Tutorials",
            "Player Homes - Castles",
            "Magic - Spells",
        ]
    ) == [
        "UI - HUD",
        "Gameplay - Immersion",
        "Modders Resources - Tutorials",
        "Player Homes - Castles",
        "Magic - Spells",
    ]


def test_sanitize_query_plan_fields_removes_transport_blobs_and_unrelated_long_terms():
    long_title = (
        "LamaKreis's Maidens of Skyrim - Serana Replacer and Lysanne Follower "
        "(High Poly) CBBE - CBBE 3BBB (3BA) - UBE and BHUNP compatible (Part 8)"
    )
    sanitized = sanitize_query_plan_fields(
        {
            "keywords": ["female", "clothing", long_title, "https://example.com/mod/1"],
            "category_hints": ["Outfits", long_title],
            "categories": ["Outfits", "Wear Armor over Devious Suits"],
        },
        query="只看天际的R18女性服装",
    )

    assert sanitized["keywords"] == ["female", "clothing"]
    assert sanitized["category_hints"] == ["Outfits"]
    assert sanitized["categories"] == ["Outfits"]


def test_sanitize_query_plan_fields_keeps_short_bracketed_mod_terms():
    sanitized = sanitize_query_plan_fields(
        {
            "requirement_terms": ["SKSE64 [AE]", "Address Library <1.6.x>"],
            "compatibility_terms": ["CBBE [3BA]", "BHUNP"],
            "keywords": ["body", "outfit"],
        },
        query="Skyrim body outfit compatible with CBBE 3BA",
    )

    assert sanitized["requirement_terms"] == ["SKSE64 [AE]", "Address Library <1.6.x>"]
    assert sanitized["compatibility_terms"] == ["CBBE [3BA]", "BHUNP"]
    assert sanitized["keywords"] == ["body", "outfit"]


def test_sanitize_query_plan_fields_drops_generic_exact_title_constraints():
    sanitized = sanitize_query_plan_fields(
        {
            "exact_title": "女性服装",
            "categories": ["Clothing", "Wear Armor over Devious Suits"],
        },
        query="只看天际的R18女性服装",
    )

    assert "exact_title" not in sanitized
    assert sanitized["categories"] == ["Clothing"]


def test_sanitize_query_plan_fields_keeps_specific_exact_title_constraints():
    sanitized = sanitize_query_plan_fields(
        {"exact_title": "Bimbo Body Morph"},
        query='Skyrim mod named "Bimbo Body Morph"',
    )

    assert sanitized["exact_title"] == "Bimbo Body Morph"


def test_sanitize_query_plan_fields_keeps_user_typed_long_exact_term_as_keyword():
    exact_title = "LamaKreis Maidens of Skyrim Serana Replacer High Poly CBBE"
    sanitized = sanitize_query_plan_fields(
        {"keywords": [exact_title]},
        query=f"查找 {exact_title}",
    )

    assert sanitized["keywords"] == [exact_title]
