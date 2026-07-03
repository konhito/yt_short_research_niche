from verticals.niche import get_caption_config, get_discovery_config, get_editing_config, get_voice_config, load_niche


def test_edge_alias_uses_edge_tts_profile_voice():
    profile = {"voice": {"suggested_voices": {"edge_tts": {"en": "gaming-voice"}}}}
    assert get_voice_config(profile, provider="edge", lang="en")["voice_id"] == "gaming-voice"


def test_discovery_config_merges_nested_defaults():
    profile = {"discovery": {"reddit": {"subreddits": ["Games"]}}}
    config = get_discovery_config(profile)
    assert config["reddit"]["subreddits"] == ["Games"]
    assert config["rss"]["feeds"] == []
    assert config["google_trends"] == {"category": "", "geo": "US"}
    assert config["youtube_trending"]["category_id"] == ""


def test_caption_config_preserves_all_style_fields():
    config = get_caption_config({"captions": {"position": "center", "background": "none"}})
    assert config["position"] == "center"
    assert config["background"] == "none"


def test_gaming_uses_meme_heavy_editing_defaults():
    config = get_editing_config(load_niche("gaming"))
    assert config["style"] == "meme_heavy"
    assert config["pexels_clips"] == [2, 4]
    assert config["meme_beats"] == [6, 10]
    assert config["youtube_clips"] == [4, 8]
    assert config["reddit_clips"] == [4, 8]
    assert config["vimeo_clips"] == [0, 4]
    assert config["vimeo_harvest_results"] == 20
    assert config["clip_review_batch_size"] == 4
    assert config["clip_review_threshold"] == 0.58
    assert config["ai_images"] == [0, 0]
    assert config["prefer_scraped_video"] is True
    assert config["cut_duration_seconds"] == [2, 5]
    assert "punch_zoom" in config["effects"]


def test_harvest_environment_overrides(monkeypatch):
    monkeypatch.setenv("VIDEO_HARVEST_ENABLED", "false")
    monkeypatch.setenv("YOUTUBE_HARVEST_DOWNLOADS", "3")
    monkeypatch.setenv("REDDIT_HARVEST_DOWNLOADS", "5")
    monkeypatch.setenv("VIMEO_HARVEST_DOWNLOADS", "2")
    monkeypatch.setenv("MINIMUM_VIDEO_CANDIDATES", "6")
    config = get_editing_config(load_niche("gaming"))

    assert config["prefer_scraped_video"] is False
    assert config["youtube_clips"][1] == 3
    assert config["reddit_clips"][1] == 5
    assert config["vimeo_clips"][1] == 2
    assert config["minimum_video_candidates"] == 6


def test_general_niche_enables_all_free_visual_sources():
    config = get_editing_config(load_niche("general"))

    assert config["prefer_scraped_video"] is True
    assert config["youtube_clips"] == [4, 8]
    assert config["reddit_clips"] == [2, 5]
    assert config["vimeo_clips"] == [2, 4]
    assert config["research_images"] == [3, 8]
    assert config["meme_beats"] == [4, 8]
