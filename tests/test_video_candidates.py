from unittest.mock import MagicMock

from PIL import Image

from verticals.video_candidates import (
    create_contact_sheet,
    deduplicate_candidates,
    enrich_candidate,
    hash_file,
    normalize_candidate,
    probe_video,
)


def test_normalize_candidate_keeps_editor_metadata():
    item = normalize_candidate({
        "source": "reddit_harvest",
        "source_id": "abc",
        "title": "GTA 6 leak reaction",
        "url": "https://reddit.com/r/gaming/comments/abc/post",
        "media_url": "https://v.redd.it/xyz",
        "duration": 31,
        "relevance_score": 24,
    })

    assert item["type"] == "harvested_video"
    assert item["status"] == "candidate"
    assert item["protected"] is True
    assert item["title"] == "GTA 6 leak reaction"


def test_deduplicate_candidates_prefers_higher_score():
    candidates = [
        {"url": "https://example.com/a", "media_hash": "same", "relevance_score": 10},
        {"url": "https://example.com/b", "media_hash": "same", "relevance_score": 20},
    ]

    result = deduplicate_candidates(candidates)

    assert len(result) == 1
    assert result[0]["url"].endswith("/b")


def test_deduplicate_candidates_uses_url_without_hash():
    candidates = [
        {"url": "https://example.com/a", "relevance_score": 10},
        {"url": "https://example.com/a", "relevance_score": 15},
    ]

    result = deduplicate_candidates(candidates)

    assert len(result) == 1
    assert result[0]["relevance_score"] == 15


def test_hash_file_matches_identical_content(tmp_path):
    one = tmp_path / "one.mp4"
    two = tmp_path / "two.mp4"
    one.write_bytes(b"same-video")
    two.write_bytes(b"same-video")

    assert hash_file(one) == hash_file(two)


def test_probe_video_reads_dimensions_and_duration(monkeypatch, tmp_path):
    result = MagicMock()
    result.stdout = '{"streams":[{"width":1080,"height":1920}],"format":{"duration":"12.5"}}'
    monkeypatch.setattr("verticals.video_candidates.run_cmd", lambda *args, **kwargs: result)

    metadata = probe_video(tmp_path / "clip.mp4")

    assert metadata == {"width": 1080, "height": 1920, "actual_duration": 12.5, "is_vertical": True}


def test_probe_video_falls_back_to_ffmpeg_stderr(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        if cmd[0] == "ffprobe":
            raise FileNotFoundError("ffprobe")
        return MagicMock(stderr="Duration: 00:00:08.50, start: 0.000000\nStream #0:0: Video: h264, yuv420p, 720x1280")

    monkeypatch.setattr("verticals.video_candidates.run_cmd", fake_run)

    metadata = probe_video(tmp_path / "clip.mp4")

    assert metadata["actual_duration"] == 8.5
    assert metadata["width"] == 720
    assert metadata["height"] == 1280


def test_create_contact_sheet_combines_three_frames(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")

    def fake_run(cmd, **kwargs):
        output = tmp_path / str(cmd[-1]).replace("\\", "/").split("/")[-1]
        Image.new("RGB", (100, 180), "red").save(output)
        return MagicMock()

    monkeypatch.setattr("verticals.video_candidates.run_cmd", fake_run)
    sheet = create_contact_sheet(clip, duration=10.0, out_path=tmp_path / "sheet.jpg")

    assert sheet.exists()
    assert Image.open(sheet).size == (300, 180)


def test_enrich_candidate_adds_media_metadata(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video")
    monkeypatch.setattr("verticals.video_candidates.probe_video", lambda _path: {"width": 720, "height": 1280, "actual_duration": 20.0, "is_vertical": True})
    monkeypatch.setattr("verticals.video_candidates.create_contact_sheet", lambda _path, duration, out_path: out_path)

    result = enrich_candidate({"path": str(clip), "url": "u", "relevance_score": 10})

    assert result["media_hash"] == hash_file(clip)
    assert result["is_vertical"] is True
    assert result["contact_sheet_path"].endswith("contact_sheet.jpg")
