from verticals.search_tags import build_search_tags_for_beat, normalize_search_tags


def test_normalize_search_tags_returns_five_unique_specific_phrases():
    draft = {
        "news": "GTA 6 map leaks",
        "youtube_title": "GTA 6 Vice City Map Leak",
        "search_tags": [
            " GTA 6 leaked Vice City map comparison ",
            "GTA 6 leaked Vice City map comparison",
            "Rockstar GTA 6 map leak fan reaction",
        ],
    }

    tags = normalize_search_tags(draft)

    assert len(tags) == 5
    assert len({tag.lower() for tag in tags}) == 5
    assert tags[0] == "GTA 6 leaked Vice City map comparison"
    assert all("GTA" in tag or "Vice City" in tag for tag in tags)


def test_normalize_search_tags_does_not_add_generic_gaming_queries():
    tags = normalize_search_tags({"news": "Nintendo Switch 2 battery test"})

    assert len(tags) == 5
    assert "rgb gaming setup" not in [tag.lower() for tag in tags]
    assert all("Nintendo Switch 2 battery test" in tag for tag in tags)


def test_build_search_tags_for_beat_uses_entities_and_intent():
    beat = {
        "script_text": "Rockstar just leaked the map and fans are furious.",
        "entities": ["Rockstar", "map", "fans"],
        "intent": "shock",
        "avoid": ["gta 5"],
    }

    tags = build_search_tags_for_beat(beat, niche="gaming")

    assert len(tags) == 5
    assert any("rockstar" in tag.lower() for tag in tags)
    assert any("fans" in tag.lower() for tag in tags)
    assert "gta 5" not in " ".join(tags).lower()
