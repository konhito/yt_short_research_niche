import json

from verticals.meme_copy import generate_meme_copy


def test_meme_writer_preserves_custom_copy_and_replaces_generic_copy(monkeypatch):
    plan = [
        {
            "type": "meme",
            "query": "microtransactions",
            "meme_text_top": "WHEN YOU HEAR GTA 6",
            "meme_text_bottom": "BUT IT IS ALL PAYWALLS",
        },
        {
            "type": "meme",
            "query": "map reveal",
            "meme_text_top": "WAIT WHAT",
            "meme_text_bottom": "IT GETS WORSE",
        },
        {
            "type": "meme",
            "query": "community split",
            "meme_text_top": "WHEN THE NEWS DROPS",
            "meme_text_bottom": "AND IT GETS WORSE",
        },
    ]
    response = {
        "memes": [
            {"index": 1, "top": "THE GTA 6 MAP", "bottom": "HAS ITS OWN ZIP CODE"},
            {"index": 2, "top": "FANS PICKING SIDES", "bottom": "BEFORE A TRAILER DROPS"},
        ]
    }
    monkeypatch.setattr("verticals.meme_copy.call_llm", lambda *args, **kwargs: json.dumps(response))

    result = generate_meme_copy(plan, "GTA 6 has a huge map and divided fans", [], provider="openai")

    assert result[0]["meme_text_top"] == "WHEN YOU HEAR GTA 6"
    assert result[1]["meme_text_top"] == "THE GTA 6 MAP"
    assert result[2]["meme_text_bottom"] == "BEFORE A TRAILER DROPS"
    assert len({item["meme_text_top"] for item in result}) == 3


def test_meme_writer_fallback_produces_unique_copy(monkeypatch):
    monkeypatch.setattr("verticals.meme_copy.call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("offline")))
    plan = [
        {"type": "meme", "query": "map", "meme_text_top": "WAIT WHAT", "meme_text_bottom": "IT GETS WORSE"},
        {"type": "meme", "query": "paywalls", "meme_text_top": "WAIT WHAT", "meme_text_bottom": "IT GETS WORSE"},
    ]

    result = generate_meme_copy(plan, "The map is enormous. Fans hate the paywalls.", [], provider="openai")

    assert result[0]["meme_text_top"] != result[1]["meme_text_top"]
    assert all(item["meme_text_bottom"] != "IT GETS WORSE" for item in result)
