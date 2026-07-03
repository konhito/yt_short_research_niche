import json

from verticals.asset_history import filter_fresh_candidates, mark_used_assets


def test_recently_used_url_is_excluded_when_fresh_candidates_exist(tmp_path):
    history_path = tmp_path / "asset_history.json"
    mark_used_assets(
        [{"source": "youtube_harvest", "url": "https://youtube.test/old"}],
        "job-old",
        history_path=history_path,
    )

    selected, rejected = filter_fresh_candidates(
        [
            {"source": "youtube_harvest", "url": "https://youtube.test/old"},
            {"source": "youtube_harvest", "url": "https://youtube.test/new"},
        ],
        max_items=1,
        history_path=history_path,
    )

    assert selected[0]["url"].endswith("/new")
    assert rejected[0]["reuse_reason"] == "used in a recent job"


def test_filter_falls_back_to_least_used_asset_when_pool_is_exhausted(tmp_path):
    history_path = tmp_path / "asset_history.json"
    old = {"source": "youtube_harvest", "url": "https://youtube.test/old"}
    older = {"source": "youtube_harvest", "url": "https://youtube.test/older"}
    mark_used_assets([old], "job-1", history_path=history_path)
    mark_used_assets([old], "job-2", history_path=history_path)
    mark_used_assets([older], "job-3", history_path=history_path)

    selected, _ = filter_fresh_candidates(
        [old, older], max_items=1, history_path=history_path
    )

    assert selected[0]["url"].endswith("/older")
    assert selected[0]["previous_use_count"] == 1


def test_mark_used_assets_records_each_asset_once_per_job(tmp_path):
    history_path = tmp_path / "asset_history.json"
    asset = {"source": "youtube_harvest", "source_id": "abc", "url": "https://youtube.test/abc"}

    mark_used_assets([asset, asset], "job-1", history_path=history_path)

    history = json.loads(history_path.read_text(encoding="utf-8"))
    entry = next(iter(history["assets"].values()))
    assert entry["used_count"] == 1
    assert entry["jobs"] == ["job-1"]
