from verticals.visual_plan import (
    apply_video_first_policy,
    enrich_pexels_search_queries,
    expand_visual_plan_for_duration,
    include_broll_prompt_assets,
    normalize_visual_plan,
    enrich_pexels_search_queries,
)


EDITING = {
    "style": "meme_heavy",
    "cut_duration_seconds": [2, 5],
    "pexels_clips": [2, 4],
    "meme_beats": [4, 6],
    "ai_images": [1, 2],
    "effects": ["punch_zoom", "pan", "shake", "hard_cut"],
}


def test_normalize_visual_plan_clamps_and_filters_items():
    draft = {"visual_plan": [
        {"type": "meme", "query": "gta", "duration_seconds": 20, "effect": "shake"},
        {"type": "wat", "query": "bad", "effect": "explode"},
    ]}
    plan = normalize_visual_plan(draft, EDITING)
    assert all(item["type"] in {"pexels", "meme", "ai_image"} for item in plan)
    assert plan[0]["duration_seconds"] == 5


def test_legacy_prompts_become_ai_timeline():
    plan = normalize_visual_plan({"broll_prompts": ["one", "two"]}, EDITING)
    assert [item["type"] for item in plan] == ["ai_image", "ai_image"]


def test_structured_plan_is_filled_to_niche_minimums():
    plan = normalize_visual_plan(
        {"news": "GTA leak", "visual_plan": [{"type": "meme", "query": "reaction"}]},
        EDITING,
    )
    counts = {kind: sum(item["type"] == kind for item in plan) for kind in ("pexels", "meme", "ai_image")}
    assert counts == {"pexels": 2, "meme": 4, "ai_image": 1}


def test_visual_plan_expands_for_audio_duration_without_reusing_same_item():
    plan = [{"type": "meme", "query": "gta leak", "duration_seconds": 3, "effect": "punch_zoom"}]
    expanded = expand_visual_plan_for_duration(plan, EDITING, duration=12)

    assert len(expanded) == 4
    assert [item["type"] for item in expanded] == ["meme", "pexels", "meme", "ai_image"]
    assert len({item["query"] for item in expanded}) == 4


def test_broll_prompts_are_preserved_as_protected_ai_assets():
    plan = [{"type": "meme", "query": "gta leak", "duration_seconds": 3, "effect": "punch_zoom"}]
    draft = {"broll_prompts": ["dramatic GTA 6 city", "controller RGB close up"]}

    merged = include_broll_prompt_assets(draft, plan, EDITING)

    assert [item["query"] for item in merged[:2]] == ["dramatic GTA 6 city", "controller RGB close up"]
    assert all(item["type"] == "ai_image" for item in merged[:2])
    assert all(item["protected"] for item in merged[:2])


def test_pexels_queries_cycle_shared_ai_search_tags_not_generic_gaming_terms():
    plan = [
        {"type": "pexels", "query": "beat one"},
        {"type": "meme", "query": "reaction"},
        {"type": "pexels", "query": "beat two"},
    ]
    tags = [f"GTA 6 exact visual {index}" for index in range(5)]

    enriched = enrich_pexels_search_queries(plan, niche="gaming", search_tags=tags)

    assert enriched[0]["search_query"] == tags[0]
    assert enriched[2]["search_query"] == tags[1]
    assert all(item.get("search_query") != "rgb gaming setup" for item in enriched)


def test_pexels_without_ai_tags_keeps_story_query_instead_of_generic_substitution():
    plan = [
        {"type": "pexels", "query": "gta 6 leaks", "duration_seconds": 3, "effect": "hard_cut"},
        {"type": "pexels", "query": "pre-order disaster backlash", "duration_seconds": 3, "effect": "hard_cut"},
    ]

    enriched = enrich_pexels_search_queries(plan, niche="gaming")

    assert enriched[0]["query"] == "gta 6 leaks"
    assert enriched[0]["topic_query"] == "gta 6 leaks"
    assert enriched[0]["search_query"] == "gta 6 leaks"
    assert enriched[1]["search_query"] == "pre-order disaster backlash"


def test_video_first_policy_removes_ai_images_when_harvest_pool_is_sufficient():
    plan = [
        {"type": "ai_image", "query": "slow image", "protected": True},
        {"type": "meme", "query": "reaction"},
        {"type": "pexels", "query": "gamer"},
    ]
    editing = {"prefer_scraped_video": True, "minimum_video_candidates": 8, "ai_images": [0, 1]}

    result = apply_video_first_policy(plan, editing, harvested_count=9)

    assert all(item["type"] != "ai_image" for item in result)


def test_video_first_policy_keeps_only_one_ai_fallback_when_pool_is_small():
    plan = [
        {"type": "ai_image", "query": "one"},
        {"type": "ai_image", "query": "two"},
        {"type": "meme", "query": "reaction"},
    ]
    editing = {"prefer_scraped_video": True, "minimum_video_candidates": 8, "ai_images": [0, 1]}

    result = apply_video_first_policy(plan, editing, harvested_count=2)

    assert sum(item["type"] == "ai_image" for item in result) == 1
