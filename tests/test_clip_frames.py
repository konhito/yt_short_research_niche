from pathlib import Path

from PIL import Image

from verticals.clip_frames import SAMPLE_RATIOS, _extract_frame, sample_clip_frames, sample_timestamps


def test_sample_timestamps_uses_six_even_positions():
    assert SAMPLE_RATIOS == (0.08, 0.24, 0.40, 0.56, 0.72, 0.88)
    assert sample_timestamps(10.0) == [0.8, 2.4, 4.0, 5.6, 7.2, 8.8]


def test_sample_clip_frames_adds_frame_metadata_and_contact_sheet(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")

    def fake_extract(_clip: Path, timestamp: float, output: Path):
        Image.new("RGB", (120, 200), (int(timestamp * 10), 40, 80)).save(output)

    monkeypatch.setattr("verticals.clip_frames._extract_frame", fake_extract)
    candidate = {"path": str(clip), "actual_duration": 10.0, "source_id": "abc"}

    result = sample_clip_frames(candidate, tmp_path / "review")

    assert len(result["sampled_frames"]) == 6
    assert result["sampled_frames"][0]["timestamp_seconds"] == 0.8
    assert result["sampled_frames"][-1]["position_ratio"] == 0.88
    assert Path(result["review_contact_sheet_path"]).exists()
    assert clip.exists()


def test_candidates_with_same_filename_use_unique_review_directories(monkeypatch, tmp_path):
    first = tmp_path / "visual_00" / "pexels_1.mp4"
    second = tmp_path / "visual_01" / "pexels_1.mp4"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_bytes(b"one")
    second.write_bytes(b"two")

    def fake_extract(_clip: Path, _timestamp: float, output: Path):
        Image.new("RGB", (120, 200), "navy").save(output)

    monkeypatch.setattr("verticals.clip_frames._extract_frame", fake_extract)
    one = sample_clip_frames({"path": str(first), "actual_duration": 10}, tmp_path / "review")
    two = sample_clip_frames({"path": str(second), "actual_duration": 10}, tmp_path / "review")

    assert Path(one["review_contact_sheet_path"]).parent != Path(two["review_contact_sheet_path"]).parent


def test_extract_frame_has_hard_timeout(monkeypatch, tmp_path):
    captured = {}

    def fake_run(_command, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("verticals.clip_frames.run_cmd", fake_run)
    _extract_frame(tmp_path / "clip.mp4", 2.0, tmp_path / "frame.jpg")

    assert captured["timeout"] == 30
