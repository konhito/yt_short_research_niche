from verticals.vision_review import score_asset_relevance


def test_score_asset_relevance_rewards_visual_overlap():
    score = score_asset_relevance(
        beat={
            "script_text": "Rockstar leaked the GTA 6 map and fans are furious.",
            "entities": ["Rockstar", "map", "fans"],
            "visual_description": "leaked game map and backlash",
            "intent": "shock",
        },
        asset={
            "title": "GTA 6 map leak reaction",
            "vision_labels": ["game map", "reaction", "fans"],
            "quality_score": 0.9,
        },
    )

    assert score["combined_score"] > 0.7
    assert score["visual_score"] > 0.4
