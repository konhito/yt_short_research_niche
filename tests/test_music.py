"""Tests for pipeline/music.py — duck filter generation, speech region merging."""

from unittest.mock import MagicMock

from verticals.music import _rank_tracks, build_duck_filter, generate_procedural_music, select_and_prepare_music


def test_rank_tracks_prefers_best_filename_tag_matches(tmp_path):
    tracks = [tmp_path / "calm-piano.mp3", tmp_path / "gaming-hype-bass.mp3"]
    assert _rank_tracks(tracks, ["gaming", "hype", "bass"]) == [tracks[1]]


def test_rank_tracks_falls_back_to_all_tracks(tmp_path):
    tracks = [tmp_path / "one.mp3", tmp_path / "two.mp3"]
    assert _rank_tracks(tracks, ["unmatched"]) == tracks


def test_generate_procedural_music_uses_plan_energy(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr("verticals.music.run_cmd", lambda cmd, **kwargs: calls.append(cmd) or MagicMock())
    out = tmp_path / "music.mp3"

    generate_procedural_music({"energy": "high", "mood": "gaming"}, 20.0, out)

    command = calls[0]
    assert "sine=frequency=110:duration=20.0" in command
    assert "tremolo=f=6" in command[command.index("-filter_complex") + 1]
    assert str(out) in command


def test_select_music_generates_track_when_library_is_empty(monkeypatch, tmp_path):
    voice = tmp_path / "voice.mp3"
    voice.write_bytes(b"voice")
    generated = tmp_path / "generated_music.mp3"
    monkeypatch.setattr("verticals.music._find_tracks", lambda: [])
    monkeypatch.setattr("verticals.music._get_audio_duration", lambda _path: 30.0)
    monkeypatch.setattr("verticals.music.generate_procedural_music", lambda plan, duration, out_path: generated)
    monkeypatch.setattr("verticals.music._get_speech_regions", lambda _path: [(0, 30)])

    result = select_and_prepare_music(voice, tmp_path, profile={"music": {"energy": "high"}})

    assert result["track_path"] == str(generated)
    assert result["duck_filter"]


class TestBuildDuckFilter:
    def test_empty_regions(self):
        result = build_duck_filter([])
        assert result == "volume=0.25"

    def test_single_region(self):
        result = build_duck_filter([(1.0, 3.0)])
        assert "volume=" in result
        assert "between(t," in result
        assert "0.12" in result
        assert "0.25" in result

    def test_multiple_regions(self, sample_speech_regions):
        result = build_duck_filter(sample_speech_regions)
        assert result.count("between(t,") == 2
        assert "0.12" in result
        assert "0.25" in result
        assert "eval=frame" in result

    def test_buffer_applied(self):
        result = build_duck_filter([(1.0, 2.0)], buffer=0.5)
        # Start should be max(0, 1.0-0.5) = 0.5
        # End should be 2.0+0.5 = 2.5
        assert "0.50" in result
        assert "2.50" in result

    def test_buffer_no_negative_start(self):
        result = build_duck_filter([(0.1, 1.0)], buffer=0.3)
        # Start should be max(0, 0.1-0.3) = 0.0
        assert "0.00" in result

    def test_returns_ffmpeg_filter_format(self, sample_speech_regions):
        result = build_duck_filter(sample_speech_regions)
        # Should be a valid ffmpeg volume filter
        assert result.startswith("volume=")
        assert ":eval=frame" in result

    def test_if_expression_structure(self):
        result = build_duck_filter([(5.0, 10.0)])
        assert "if(" in result
        assert ", 0.12, 0.25)" in result
