import time

from verticals.video_harvest import harvest_video_sources


def test_video_sources_harvest_in_parallel(monkeypatch, tmp_path):
    def youtube(*args, **kwargs):
        time.sleep(0.12)
        return {"assets": [{"source": "youtube_harvest", "url": "yt", "relevance_score": 20}], "rejected": [], "manifest_path": "yt.json"}

    def reddit(*args, **kwargs):
        time.sleep(0.12)
        return {"assets": [{"source": "reddit_harvest", "url": "rd", "relevance_score": 18}], "rejected": [], "manifest_path": "rd.json"}

    monkeypatch.setattr("verticals.video_harvest.harvest_topic_shorts", youtube)
    monkeypatch.setattr("verticals.video_harvest.harvest_reddit_videos", reddit)

    started = time.perf_counter()
    result = harvest_video_sources(
        {"youtube_title": "GTA 6"},
        tmp_path,
        niche="gaming",
        editing={"youtube_clips": [4, 8], "reddit_clips": [4, 8]},
        subreddits=["gaming"],
    )
    elapsed = time.perf_counter() - started

    assert {asset["source"] for asset in result["assets"]} == {"youtube_harvest", "reddit_harvest"}
    assert elapsed < 0.21
    assert result["manifests"] == {"youtube": "yt.json", "reddit": "rd.json"}
