from pathlib import Path

from verticals.video_inspection import inspect_media_file


def test_inspect_media_file_returns_hash_dimensions_and_contact_sheet(monkeypatch, tmp_path):
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"video-bytes")

    monkeypatch.setattr(
        "verticals.video_inspection.probe_video",
        lambda path: {"width": 1080, "height": 1920, "actual_duration": 11.5, "is_vertical": True},
    )
    monkeypatch.setattr(
        "verticals.video_inspection.hash_file",
        lambda path: "abc123",
    )
    monkeypatch.setattr(
        "verticals.video_inspection.create_contact_sheet",
        lambda path, duration, out_path: out_path.write_text("sheet", encoding="utf-8") or out_path,
    )

    info = inspect_media_file(clip)

    assert info["path"] == str(clip)
    assert info["media_hash"] == "abc123"
    assert info["width"] == 1080
    assert info["height"] == 1920
    assert info["contact_sheet_path"].endswith("contact_sheet.jpg")
