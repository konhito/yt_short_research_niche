from verticals.timeline_validation import validate_semantic_timeline


def test_validate_semantic_timeline_rejects_repeated_opening_asset():
    timeline = [
        {"asset_id": "asset_001", "start": 0.0, "end": 2.0, "source": "youtube_harvest"},
        {"asset_id": "asset_001", "start": 2.0, "end": 4.0, "source": "youtube_harvest"},
    ]

    report = validate_semantic_timeline(timeline, duration=4.0)

    assert report["valid"] is False
    assert any("repeated asset" in error for error in report["errors"])


def test_validate_semantic_timeline_flags_short_coverage():
    timeline = [{"asset_id": "asset_001", "start": 0.0, "end": 1.0, "source": "imgflip"}]

    report = validate_semantic_timeline(timeline, duration=4.0)

    assert report["valid"] is False
    assert any("coverage" in warning for warning in report["warnings"])
