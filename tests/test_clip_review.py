import json
from pathlib import Path

from verticals.clip_review import (
    is_reviewable_video,
    prepare_video_candidates_for_review,
    review_video_candidates,
    validate_review_decision,
)


def _candidate(tmp_path, name="clip", score=20, accepted=True):
    path = tmp_path / f"{name}.mp4"
    path.write_bytes(b"video")
    sheet = tmp_path / f"{name}.jpg"
    sheet.write_bytes(b"jpg")
    return {
        "source_id": name,
        "path": str(path),
        "source": "youtube_harvest",
        "actual_duration": 10.0,
        "relevance_score": score,
        "quality_score": 0.8,
        "accepted": accepted,
        "review_contact_sheet_path": str(sheet),
        "sampled_frames": [{"timestamp_seconds": 4.0}],
    }


def test_validate_review_decision_clamps_ranges_and_discards_wrong_topic(tmp_path):
    candidate = _candidate(tmp_path)
    decision = validate_review_decision(candidate, {
        "asset_id": "clip",
        "decision": "keep",
        "relevance_score": 0.9,
        "quality_score": 0.8,
        "reason": "Wrong story",
        "matched_beat_ids": ["beat_1"],
        "useful_ranges": [
            {"start": -2, "end": 2, "reason": "intro"},
            {"start": 9.8, "end": 20, "reason": "too short after clamp"},
        ],
        "warnings": ["wrong_topic"],
    })

    assert decision["review_decision"] == "discard"
    assert decision["approved_source_ranges"] == [{"start": 0.0, "end": 2.0, "reason": "intro"}]


def test_review_keeps_files_and_excludes_discarded_assets(monkeypatch, tmp_path):
    candidates = [_candidate(tmp_path, "keep"), _candidate(tmp_path, "drop")]

    def fake_review(batch, **_kwargs):
        return {"clips": [
            {
                "asset_id": "keep", "decision": "keep", "relevance_score": 0.9,
                "quality_score": 0.8, "reason": "matches", "visual_description": "Claude UI",
                "matched_beat_ids": ["beat_1"],
                "useful_ranges": [{"start": 1, "end": 5, "reason": "useful"}], "warnings": [],
            },
            {
                "asset_id": "drop", "decision": "discard", "relevance_score": 0.1,
                "quality_score": 0.8, "reason": "unrelated", "visual_description": "book",
                "matched_beat_ids": [], "useful_ranges": [], "warnings": ["wrong_topic"],
            },
        ]}

    monkeypatch.setattr("verticals.clip_review.call_openai_clip_review", fake_review)
    result = review_video_candidates(
        {"script": "Anthropic released Claude", "script_beats": [{"beat_id": "beat_1"}]},
        [], candidates, tmp_path / "reviews", batch_size=4,
    )

    assert [item["source_id"] for item in result["approved"]] == ["keep"]
    assert [item["source_id"] for item in result["discarded"]] == ["drop"]
    assert all(Path(item["path"]).exists() for item in candidates)
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert len(manifest["discarded"]) == 1


def test_review_falls_back_per_failed_batch(monkeypatch, tmp_path):
    candidates = [_candidate(tmp_path, "one", score=20), _candidate(tmp_path, "two", score=1)]

    def fail_review(*_args, **_kwargs):
        raise RuntimeError("offline")

    monkeypatch.setattr("verticals.clip_review.call_openai_clip_review", fail_review)
    result = review_video_candidates({}, [], candidates, tmp_path / "reviews", batch_size=1)

    assert result["approved"][0]["source_id"] == "one"
    assert result["approved"][0]["review_mode"] == "metadata_fallback"
    assert result["discarded"][0]["source_id"] == "two"
    assert result["fallback_count"] == 2


def test_prepare_samples_candidates_before_review(monkeypatch, tmp_path):
    candidates = [_candidate(tmp_path, "one"), _candidate(tmp_path, "two")]

    def fake_sample(candidate, _out_dir):
        return {**candidate, "review_contact_sheet_path": f"{candidate['source_id']}.jpg"}

    def fake_review(_draft, _words, sampled, _out_dir, **_kwargs):
        assert {item["source_id"] for item in sampled} == {"one", "two"}
        assert all(item.get("review_contact_sheet_path") for item in sampled)
        return {"approved": sampled, "discarded": [], "manifest_path": "review.json"}

    monkeypatch.setattr("verticals.clip_review.sample_clip_frames", fake_sample)
    monkeypatch.setattr("verticals.clip_review.review_video_candidates", fake_review)

    result = prepare_video_candidates_for_review({}, [], candidates, tmp_path / "review", workers=2)

    assert len(result["approved"]) == 2


def test_review_uses_metadata_fallback_when_contact_sheet_is_missing(monkeypatch, tmp_path):
    candidate = _candidate(tmp_path, "missing")
    Path(candidate["review_contact_sheet_path"]).unlink()
    called = False

    def should_not_call(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("vision must not review a clip without frames")

    monkeypatch.setattr("verticals.clip_review.call_openai_clip_review", should_not_call)
    result = review_video_candidates({}, [], [candidate], tmp_path / "reviews")

    assert called is False
    assert result["approved"][0]["review_mode"] == "metadata_fallback"


def test_reviewable_video_includes_stock_and_harvested_clips():
    assert is_reviewable_video({"path": "pexels.mp4", "source": "pexels"}) is True
    assert is_reviewable_video({"path": "reddit.webm", "source": "reddit_harvest"}) is True
    assert is_reviewable_video({"path": "meme.jpg", "source": "imgflip"}) is False
