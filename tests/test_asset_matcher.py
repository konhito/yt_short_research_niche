from verticals.asset_matcher import match_assets_to_beats


def test_match_assets_to_beats_prefers_fresh_nonrepeating_assets():
    beats = [{"beat_id": "beat_001", "intent": "shock", "entities": ["rockstar"]}]
    assets = [
        {"asset_id": "asset_001", "source": "youtube_harvest", "combined_score": 0.8, "freshness_penalty": 0.0},
        {"asset_id": "asset_002", "source": "imgflip", "combined_score": 0.7, "freshness_penalty": 0.4},
    ]

    plan = match_assets_to_beats(beats, assets)

    assert plan[0]["selected_asset"]["asset_id"] == "asset_001"
    assert plan[0]["ranked_assets"][0]["asset_id"] == "asset_001"
