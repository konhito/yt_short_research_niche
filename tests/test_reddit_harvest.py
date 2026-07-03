import json
from pathlib import Path
from unittest.mock import MagicMock

from verticals.reddit_harvest import (
    build_reddit_queries,
    harvest_reddit_videos,
    score_reddit_candidate,
    search_reddit_videos,
)


def test_build_reddit_queries_uses_draft_entities():
    draft = {
        "youtube_title": "GTA 6 Rockstar Leak Backlash",
        "script": "Fans are angry at Rockstar over GTA 6 leaks.",
    }

    queries = build_reddit_queries(draft, "gaming")

    assert "GTA" in queries[0]
    assert "Rockstar" in queries[0]


def test_build_reddit_queries_uses_shared_ai_search_tags_without_hardcoded_gaming_terms():
    tags = [f"specific story search {index}" for index in range(5)]

    queries = build_reddit_queries({"search_tags": tags}, "gaming")

    assert queries == tags


def test_search_reddit_videos_uses_pullpush_video_filters(monkeypatch):
    captured = {}
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"data": []}

    def fake_get(url, **kwargs):
        captured["url"] = url
        captured["kwargs"] = kwargs
        return response

    monkeypatch.setattr("verticals.reddit_harvest.requests.get", fake_get)

    search_reddit_videos("GTA 6", ["gaming"], size=25, after="30d")

    assert captured["url"].endswith("/reddit/search/submission/")
    params = captured["kwargs"]["params"]
    assert params["is_video"] == "true"
    assert params["over_18"] == "false"
    assert params["sort_type"] == "score"
    assert params["after"] == "30d"


def test_score_reddit_candidate_prefers_relevant_gaming_video():
    draft = {"youtube_title": "GTA 6 Rockstar Leak", "script": "GTA 6 leak backlash"}
    good = {
        "title": "GTA 6 leak has gamers angry",
        "subreddit": "gaming",
        "score": 900,
        "num_comments": 120,
        "is_video": True,
        "url": "https://v.redd.it/good",
    }
    bad = {
        "title": "GTA 5 mod compilation",
        "subreddit": "funny",
        "score": 2,
        "num_comments": 0,
        "is_video": True,
        "url": "https://v.redd.it/bad",
    }

    assert score_reddit_candidate(good, draft, "GTA 6") > score_reddit_candidate(bad, draft, "GTA 6")


def test_harvest_reddit_videos_downloads_candidates(monkeypatch, tmp_path):
    submission = {
        "id": "abc123",
        "title": "GTA 6 leak reaction",
        "subreddit": "gaming",
        "score": 1000,
        "num_comments": 250,
        "is_video": True,
        "permalink": "/r/gaming/comments/abc123/gta_6_leak/",
        "url": "https://v.redd.it/media123",
        "created_utc": 1783030000,
    }
    monkeypatch.setattr("verticals.reddit_harvest.search_reddit_videos", lambda *args, **kwargs: [submission])
    monkeypatch.setattr("verticals.reddit_harvest._yt_dlp_base_cmd", lambda: ["yt-dlp"])

    def fake_run(cmd, **kwargs):
        output = Path(cmd[cmd.index("-o") + 1].replace("%(id)s.%(ext)s", "abc123.mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"reddit-video")
        return MagicMock(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("verticals.reddit_harvest.subprocess.run", fake_run)

    result = harvest_reddit_videos(
        {"youtube_title": "GTA 6 Leak", "script": "Rockstar GTA 6 leak"},
        tmp_path,
        niche="gaming",
        subreddits=["gaming"],
        max_downloads=1,
        min_score=1,
    )

    asset = result["assets"][0]
    assert asset["source"] == "reddit_harvest"
    assert asset["protected"] is False
    assert asset["status"] == "candidate"
    assert asset["subreddit"] == "gaming"
    assert Path(result["manifest_path"]).exists()
    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["assets"][0]["source_id"] == "abc123"
