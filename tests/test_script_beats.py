from verticals.script_beats import align_transcript_to_beats, build_script_beats


def test_build_script_beats_returns_structured_beats():
    beats = build_script_beats(
        "GTA 6 leaks are everywhere. Rockstar is silent.",
        niche="gaming",
    )

    assert [beat["beat_id"] for beat in beats] == ["beat_001", "beat_002"]
    assert all(len(beat["search_queries"]) == 3 for beat in beats)
    assert beats[0]["script_text"] == "GTA 6 leaks are everywhere."
    assert beats[0]["preferred_types"] == ["youtube_harvest", "imgflip", "web_research"]


def test_align_transcript_to_beats_groups_words_by_pause_boundaries():
    words = [
        {"word": "GTA", "start": 0.0, "end": 0.2},
        {"word": "6", "start": 0.2, "end": 0.3},
        {"word": "leaks", "start": 0.3, "end": 0.5},
        {"word": "Rockstar", "start": 1.2, "end": 1.5},
        {"word": "is", "start": 1.5, "end": 1.6},
        {"word": "silent", "start": 1.6, "end": 1.9},
    ]
    beats = [
        {"beat_id": "beat_001", "start": 0.0, "end": 1.0},
        {"beat_id": "beat_002", "start": 1.0, "end": 2.0},
    ]

    aligned = align_transcript_to_beats(words, beats)

    assert aligned[0]["transcript_text"] == "GTA 6 leaks"
    assert aligned[0]["start"] == 0.0
    assert aligned[0]["end"] == 0.5
    assert aligned[1]["transcript_text"] == "Rockstar is silent"
    assert aligned[1]["start"] == 1.2
    assert aligned[1]["end"] == 1.9
