from unittest.mock import MagicMock

import pytest

from verticals.mcp_assets import (
    _rotated_selection,
    fetch_local_footage,
    fetch_pexels_footage,
    fetch_pixabay_footage,
)


def test_ranked_stock_pool_rotates_between_job_seeds():
    urls = [f"https://cdn.test/{index}.mp4" for index in range(12)]

    choices = {_rotated_selection(urls, 1, f"job-{index}")[0] for index in range(10)}

    assert len(choices) > 1


def test_fetch_pexels_footage_uses_rest_api(monkeypatch, tmp_path):
    calls = {}

    search_response = MagicMock()
    search_response.raise_for_status.return_value = None
    search_response.json.return_value = {
        "videos": [
            {
                "video_files": [
                    {"link": "https://videos.pexels.com/wide.mp4", "width": 1920, "height": 1080},
                    {"link": "https://videos.pexels.com/portrait.mp4", "width": 1080, "height": 1920},
                ]
            }
        ]
    }
    video_response = MagicMock()
    video_response.raise_for_status.return_value = None
    video_response.iter_content.return_value = [b"video"]

    def fake_get(url, **kwargs):
        if url == "https://api.pexels.com/videos/search":
            calls["search"] = kwargs
            return search_response
        calls["download_url"] = url
        return video_response

    monkeypatch.setenv("PEXELS_API_KEY", "pexels-key")
    monkeypatch.setattr("verticals.mcp_assets.requests.get", fake_get)
    monkeypatch.setattr("verticals.mcp_assets.log", lambda _msg: None)

    clips = fetch_pexels_footage("gta trailer", tmp_path, limit=1)

    assert calls["search"]["headers"]["Authorization"] == "pexels-key"
    assert calls["search"]["params"]["query"] == "gta trailer"
    assert calls["search"]["params"]["orientation"] == "portrait"
    assert calls["download_url"] == "https://videos.pexels.com/portrait.mp4"
    assert clips[0].read_bytes() == b"video"


def test_fetch_pexels_footage_requires_api_key(monkeypatch, tmp_path):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.setattr("verticals.mcp_assets.log", lambda _msg: None)
    with pytest.raises(RuntimeError, match="PEXELS_API_KEY"):
        fetch_pexels_footage("gaming", tmp_path, limit=1)


def test_fetch_pixabay_footage_uses_video_api(monkeypatch, tmp_path):
    calls = {}

    search_response = MagicMock()
    search_response.raise_for_status.return_value = None
    search_response.json.return_value = {
        "hits": [
            {
                "videos": {
                    "large": {"url": "https://pixabay.com/wide.mp4", "width": 1920, "height": 1080},
                    "medium": {"url": "https://pixabay.com/portrait.mp4", "width": 720, "height": 1280},
                }
            }
        ]
    }
    video_response = MagicMock()
    video_response.raise_for_status.return_value = None
    video_response.iter_content.return_value = [b"pixabay-video"]

    def fake_get(url, **kwargs):
        if url == "https://pixabay.com/api/videos/":
            calls["search"] = kwargs
            return search_response
        calls["download_url"] = url
        return video_response

    monkeypatch.setenv("PIXABAY_API_KEY", "pixabay-key")
    monkeypatch.setattr("verticals.mcp_assets.requests.get", fake_get)
    monkeypatch.setattr("verticals.mcp_assets.log", lambda _msg: None)

    clips = fetch_pixabay_footage("angry gamer reaction", tmp_path, limit=1)

    assert calls["search"]["params"]["key"] == "pixabay-key"
    assert calls["search"]["params"]["q"] == "angry gamer reaction"
    assert calls["search"]["params"]["safesearch"] == "true"
    assert calls["download_url"] == "https://pixabay.com/portrait.mp4"
    assert clips[0].read_bytes() == b"pixabay-video"


def test_fetch_local_footage_copies_matching_clip(tmp_path):
    root = tmp_path / "assets"
    source = root / "gaming" / "angry" / "angry_gamer_reaction.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"local-video")

    out_dir = tmp_path / "work"
    clips = fetch_local_footage("angry gamer reaction", out_dir, niche="gaming", limit=1, roots=[root])

    assert clips[0].read_bytes() == b"local-video"
    assert clips[0].parent == out_dir
