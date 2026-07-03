import json
from pathlib import Path

from verticals.yt_harvest import (
    build_shorts_queries,
    harvest_topic_shorts,
    parse_yt_dlp_json_lines,
    score_candidate,
)


def test_build_shorts_queries_uses_draft_entities_not_raw_topic_only():
    draft = {
        "news": "gta leaks",
        "niche": "gaming",
        "youtube_title": "GTA 6 Leaks: Rockstar Backlash",
        "script": "Rockstar is facing GTA 6 leak backlash and preorder drama.",
    }

    queries = build_shorts_queries(draft, "gaming", max_queries=5)

    assert any("Rockstar" in query for query in queries)
    assert "gta leaks shorts" in queries
    assert queries[0] != "gta leaks"


def test_build_shorts_queries_uses_shared_ai_search_tags_without_generic_queries():
    draft = {
        "search_tags": [
            "GTA 6 leaked Vice City map comparison",
            "Rockstar GTA 6 map leak fan reaction",
            "GTA 6 Vice City map size analysis",
            "GTA 6 leaked locations gameplay footage",
            "GTA 6 map leak Reddit discussion",
        ]
    }

    queries = build_shorts_queries(draft, "gaming")

    assert queries[:5] == [f"{tag} shorts" for tag in draft["search_tags"]]
    assert not any(query in {"gaming news reaction shorts", "angry gamer reaction shorts"} for query in queries)


def test_score_candidate_prefers_relevant_short_results():
    draft = {
        "youtube_title": "GTA 6 Leaks: Rockstar Backlash",
        "script": "Rockstar is facing GTA 6 leak backlash.",
    }
    good = {
        "title": "GTA 6 leaks have gamers angry #shorts",
        "duration": 42,
        "webpage_url": "https://youtube.com/shorts/abc",
    }
    bad = {
        "title": "GTA 5 funny moments compilation",
        "duration": 620,
        "webpage_url": "https://youtube.com/watch?v=def",
    }

    assert score_candidate(good, draft, "GTA 6 leaks shorts") > score_candidate(bad, draft, "GTA 6 leaks shorts")


def test_parse_yt_dlp_json_lines_skips_bad_lines():
    lines = "\n".join([
        json.dumps({"title": "one", "webpage_url": "u1"}),
        "not json",
        json.dumps({"title": "two", "webpage_url": "u2"}),
    ])

    assert [item["title"] for item in parse_yt_dlp_json_lines(lines)] == ["one", "two"]


def test_harvest_topic_shorts_searches_scores_and_downloads(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, capture_output=True, text=True, timeout=120, check=False):
        calls.append(cmd)
        class Result:
            returncode = 0
            stderr = ""
        result = Result()
        if "--skip-download" in cmd:
            result.stdout = "\n".join([
                json.dumps({
                    "id": "good",
                    "title": "GTA 6 leaks angry gamer reaction #shorts",
                    "duration": 34,
                    "webpage_url": "https://youtube.com/shorts/good",
                    "uploader": "Creator",
                }),
                json.dumps({
                    "id": "bad",
                    "title": "GTA 5 mods long video",
                    "duration": 700,
                    "webpage_url": "https://youtube.com/watch?v=bad",
                }),
            ])
        else:
            result.stdout = ""
            output_index = cmd.index("-o") + 1
            Path(cmd[output_index].replace("%(id)s.%(ext)s", "good.mp4")).write_bytes(b"video")
        return result

    monkeypatch.setattr("verticals.yt_harvest.shutil.which", lambda name: "yt-dlp")
    monkeypatch.setattr("verticals.yt_harvest.subprocess.run", fake_run)

    result = harvest_topic_shorts(
        {"youtube_title": "GTA 6 Leaks", "script": "Rockstar GTA 6 leaks"},
        tmp_path,
        niche="gaming",
        max_results=2,
        max_downloads=1,
    )

    assert result["assets"][0]["source"] == "youtube_harvest"
    assert result["assets"][0]["status"] == "candidate"
    assert result["assets"][0]["protected"] is False
    assert result["rejected"][0]["reason"]
    assert (tmp_path / "harvest_manifest.json").exists()
    assert any("ytsearch2:" in cmd[1] for cmd in calls if "--skip-download" in cmd)


def test_harvest_topic_shorts_skips_recently_used_result(monkeypatch, tmp_path):
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append(cmd)
        result = type("Result", (), {"returncode": 0, "stderr": "", "stdout": ""})()
        if "--skip-download" in cmd:
            result.stdout = "\n".join([
                json.dumps({"id": "old", "title": "GTA 6 leak #shorts", "duration": 20,
                            "webpage_url": "https://youtube.test/old"}),
                json.dumps({"id": "fresh", "title": "GTA 6 leak reaction #shorts", "duration": 21,
                            "webpage_url": "https://youtube.test/fresh"}),
            ])
        else:
            output = Path(cmd[cmd.index("-o") + 1].replace("%(id)s.%(ext)s", "fresh.mp4"))
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_bytes(b"fresh-video")
        return result

    monkeypatch.setattr("verticals.yt_harvest.shutil.which", lambda name: "yt-dlp")
    monkeypatch.setattr("verticals.yt_harvest.subprocess.run", fake_run)

    result = harvest_topic_shorts(
        {"youtube_title": "GTA 6 Leak", "script": "GTA 6 leak", "job_id": "job-new"},
        tmp_path / "clips",
        max_results=2,
        max_downloads=1,
        history_path=tmp_path / "history.json",
    )
    from verticals.asset_history import mark_used_assets
    # Re-run after recording the first selected clip; the next result must be fresh.
    mark_used_assets(result["assets"], "job-1", history_path=tmp_path / "history.json")
    second = harvest_topic_shorts(
        {"youtube_title": "GTA 6 Leak", "script": "GTA 6 leak", "job_id": "job-new-2"},
        tmp_path / "clips-2",
        max_results=2,
        max_downloads=1,
        history_path=tmp_path / "history.json",
    )

    assert second["assets"][0]["source_id"] != result["assets"][0]["source_id"]
