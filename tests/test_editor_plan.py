from verticals.editor_plan import (
    _build_editor_prompt,
    build_asset_manifest,
    build_fallback_editor_timeline,
    validate_editor_timeline,
)


def test_fallback_editor_timeline_uses_unique_assets_without_looping():
    assets = [
        {"path": "a.mp4", "type": "pexels", "source": "pexels", "query": "gta leak"},
        {"path": "b.jpg", "type": "meme", "source": "imgflip", "query": "reaction"},
        {"path": "c.png", "type": "ai_image", "source": "openai", "query": "console"},
    ]
    manifest = build_asset_manifest(assets)

    timeline = build_fallback_editor_timeline(manifest, duration=12.0)

    assert [item["asset_id"] for item in timeline] == ["asset_001", "asset_002", "asset_003"]
    assert sum(item["duration_seconds"] for item in timeline) == 12.0


def test_editor_timeline_rejects_duplicate_asset_without_reuse_reason():
    assets = build_asset_manifest([
        {"path": "a.mp4", "type": "pexels", "source": "pexels", "query": "gta leak"},
    ])
    raw = [
        {"asset_id": "asset_001", "start": 0, "end": 2, "effect": "hard_cut"},
        {"asset_id": "asset_001", "start": 2, "end": 4, "effect": "hard_cut"},
    ]

    timeline = validate_editor_timeline(raw, assets, duration=4.0)

    assert len(timeline) == 1
    assert timeline[0]["asset_id"] == "asset_001"


def test_editor_timeline_allows_duplicate_asset_with_reuse_reason():
    assets = build_asset_manifest([
        {"path": "a.mp4", "type": "pexels", "source": "pexels", "query": "gta leak"},
    ])
    raw = [
        {"asset_id": "asset_001", "start": 0, "end": 2, "effect": "hard_cut"},
        {
            "asset_id": "asset_001",
            "start": 2,
            "end": 4,
            "effect": "hard_cut",
            "reuse_reason": "callback to the opening leak footage",
        },
    ]

    timeline = validate_editor_timeline(raw, assets, duration=4.0)

    assert len(timeline) == 2
    assert timeline[1]["reuse_reason"] == "callback to the opening leak footage"


def test_editor_timeline_retunes_partial_output_to_full_duration():
    assets = build_asset_manifest([
        {"path": "a.mp4", "type": "pexels", "source": "pexels", "query": "gta leak"},
        {"path": "b.png", "type": "ai_image", "source": "openai", "query": "broll"},
    ])
    raw = [
        {"asset_id": "asset_001", "start": 0, "end": 2, "effect": "hard_cut"},
        {"asset_id": "asset_002", "start": 2, "end": 4, "effect": "pan"},
    ]

    timeline = validate_editor_timeline(raw, assets, duration=10.0)

    assert timeline[0]["start"] == 0
    assert timeline[-1]["end"] == 10.0
    assert sum(item["duration_seconds"] for item in timeline) == 10.0


def test_editor_timeline_adds_missing_protected_assets_before_retime():
    assets = build_asset_manifest([
        {"path": "a.mp4", "type": "pexels", "source": "pexels", "query": "clip"},
        {
            "path": "b.png",
            "type": "ai_image",
            "source": "openai",
            "query": "original broll prompt",
            "protected": True,
        },
    ])
    raw = [{"asset_id": "asset_001", "start": 0, "end": 4, "effect": "hard_cut"}]

    timeline = validate_editor_timeline(raw, assets, duration=8.0)

    assert [item["asset_id"] for item in timeline] == ["asset_001", "asset_002"]
    assert timeline[-1]["end"] == 8.0


def test_manifest_preserves_youtube_metadata_and_protection():
    manifest = build_asset_manifest([
        {
            "path": "yt.mp4",
            "type": "youtube_short",
            "source": "youtube_harvest",
            "title": "GTA 6 leak reaction",
            "url": "https://youtube.com/shorts/abc",
            "uploader": "Creator",
            "protected": True,
            "relevance_score": 22,
        }
    ])

    assert manifest[0]["title"] == "GTA 6 leak reaction"
    assert manifest[0]["url"] == "https://youtube.com/shorts/abc"
    assert manifest[0]["protected"] is True


def test_editor_prompt_includes_timed_transcript_segments():
    prompt = _build_editor_prompt(
        {"script": "one two three four five six", "youtube_title": "T", "niche": "gaming"},
        [
            {"word": "one", "start": 0.0, "end": 0.2},
            {"word": "two", "start": 0.2, "end": 0.4},
            {"word": "three", "start": 0.4, "end": 0.6},
            {"word": "four", "start": 0.6, "end": 0.8},
            {"word": "five", "start": 0.8, "end": 1.0},
            {"word": "six", "start": 1.0, "end": 1.2},
        ],
        [],
        {},
        1.2,
        {"style": "meme_heavy"},
    )

    assert "transcript_segments" in prompt
    assert "one two three four five six" in prompt
    assert "Use more youtube_harvest and meme assets" in prompt


def test_editor_prompt_includes_source_targets_and_reddit_metadata():
    assets = build_asset_manifest([{
        "path": "reddit.mp4",
        "type": "harvested_video",
        "source": "reddit_harvest",
        "title": "GTA 6 reaction",
        "subreddit": "gaming",
        "contact_sheet_path": "sheet.jpg",
        "actual_duration": 22.0,
        "relevance_score": 30,
    }])

    prompt = _build_editor_prompt(
        {"script": "GTA 6 reaction", "youtube_title": "T", "niche": "gaming"},
        [{"word": "GTA", "start": 0, "end": 0.3}],
        assets,
        {},
        10,
        {"youtube_clips": [4, 8], "reddit_clips": [4, 8], "meme_beats": [6, 10], "ai_images": [0, 1]},
    )

    assert '"reddit_harvest": {"minimum": 4, "maximum": 8}' in prompt
    assert '"subreddit": "gaming"' in prompt
    assert '"contact_sheet_path": "sheet.jpg"' in prompt
    assert "source_start_seconds" in prompt


def test_editor_validation_clamps_source_range_to_clip_duration():
    assets = build_asset_manifest([{
        "path": "yt.mp4",
        "type": "harvested_video",
        "source": "youtube_harvest",
        "actual_duration": 12.0,
    }])
    raw = [{
        "asset_id": "asset_001",
        "start": 0,
        "end": 3,
        "source_start_seconds": 20,
    }]

    timeline = validate_editor_timeline(raw, assets, duration=3.0)

    assert timeline[0]["source_start_seconds"] == 9.0


def test_editor_validation_rejects_duplicate_meme_file_across_asset_ids():
    assets = build_asset_manifest([
        {"path": "same.jpg", "type": "meme", "source": "imgflip"},
        {"path": "same.jpg", "type": "meme", "source": "imgflip"},
    ])
    raw = [
        {"asset_id": "asset_001", "start": 0, "end": 2},
        {"asset_id": "asset_002", "start": 2, "end": 4},
    ]

    timeline = validate_editor_timeline(raw, assets, duration=4.0)

    assert len(timeline) == 1
