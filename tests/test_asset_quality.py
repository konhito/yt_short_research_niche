from verticals.asset_quality import evaluate_asset_quality


def test_evaluate_asset_quality_rejects_watermark_and_landscape():
    asset = {
        "width": 1920,
        "height": 1080,
        "watermark_score": 0.9,
        "duplicate_score": 0.1,
    }

    result = evaluate_asset_quality(asset)

    assert result["accepted"] is False
    assert "watermark" in result["reasons"]
    assert "landscape" in result["reasons"]


def test_evaluate_asset_quality_accepts_strong_vertical_asset():
    asset = {
        "width": 1080,
        "height": 1920,
        "watermark_score": 0.0,
        "duplicate_score": 0.1,
    }

    result = evaluate_asset_quality(asset)

    assert result["accepted"] is True
    assert result["quality_score"] > 0.5
