"""Tests for pipeline/assemble.py — audio duration parsing."""

from unittest.mock import patch, MagicMock
from pathlib import Path

from verticals.assemble import get_audio_duration, _escape_ffmpeg_filter_path
from verticals import assemble


class TestGetAudioDuration:
    @patch("verticals.assemble.run_cmd")
    def test_parses_duration(self, mock_cmd):
        mock_result = MagicMock()
        mock_result.stdout = "65.432000\n"
        mock_cmd.return_value = mock_result

        duration = get_audio_duration(Path("/tmp/test.mp3"))
        assert abs(duration - 65.432) < 0.001

    @patch("verticals.assemble.run_cmd")
    def test_parses_short_duration(self, mock_cmd):
        mock_result = MagicMock()
        mock_result.stdout = "3.5\n"
        mock_cmd.return_value = mock_result

        duration = get_audio_duration(Path("/tmp/test.mp3"))
        assert abs(duration - 3.5) < 0.001

    @patch("verticals.assemble.run_cmd")
    def test_calls_ffprobe(self, mock_cmd):
        mock_result = MagicMock()
        mock_result.stdout = "10.0\n"
        mock_cmd.return_value = mock_result

        audio_path = Path("/tmp/audio.mp3")
        get_audio_duration(audio_path)
        args = mock_cmd.call_args[0][0]
        assert "ffprobe" in args
        assert str(audio_path) in args

    def test_escapes_windows_path_for_ffmpeg(self):
        path = Path(r"C:\Users\konhi\.verticals\media\work_1783020636_en\captions_en.ass")
        escaped = _escape_ffmpeg_filter_path(path)
        assert escaped == r"C\:/Users/konhi/.verticals/media/work_1783020636_en/captions_en.ass"

    @patch("verticals.assemble._ffmpeg_has_libass", return_value=True)
    @patch("verticals.assemble.animate_frame")
    @patch("verticals.assemble.get_audio_duration", return_value=6.0)
    @patch("verticals.assemble.run_cmd")
    def test_assembly_retries_without_ass_filter(self, mock_run_cmd, mock_duration, mock_anim, mock_libass, tmp_path):
        frames = [tmp_path / "f1.png"]
        frames[0].write_bytes(b"png")
        voice = tmp_path / "voice.mp3"
        voice.write_bytes(b"mp3")
        ass = tmp_path / "captions.ass"
        ass.write_text("dummy", encoding="utf-8")

        def side_effect(cmd, check=True, capture=False, **kwargs):
            if "-vf" in cmd and any(str(item).startswith("ass=") for item in cmd):
                raise RuntimeError("burn-in failed")
            return MagicMock(stdout="")

        mock_run_cmd.side_effect = side_effect

        out = assemble.assemble_video(
            frames=frames,
            voiceover=voice,
            out_dir=tmp_path,
            job_id="job",
            ass_path=str(ass),
        )

        assert out.name == "verticals_job_en.mp4"
        assert mock_run_cmd.call_count >= 3

    @patch("verticals.assemble.animate_frame")
    @patch("verticals.assemble.get_audio_duration", return_value=8.0)
    @patch("verticals.assemble.run_cmd", return_value=MagicMock(stdout=""))
    def test_assembly_uses_timeline_durations_and_effects(self, _run, _duration, animate, tmp_path):
        image = tmp_path / "meme.jpg"
        image.write_bytes(b"jpg")
        voice = tmp_path / "voice.mp3"
        voice.write_bytes(b"mp3")
        timeline = [{"path": str(image), "duration_seconds": 3, "effect": "shake", "source": "openai"}]
        assemble.assemble_video([], voice, tmp_path, "timeline", timeline=timeline)
        assert animate.call_count == 1
        assert animate.call_args_list[0].args[3] == "shake"

    @patch("verticals.assemble.animate_frame")
    @patch("verticals.assemble.animate_meme_frame")
    @patch("verticals.assemble.get_audio_duration", return_value=4.0)
    @patch("verticals.assemble.run_cmd", return_value=MagicMock(stdout=""))
    def test_assembly_fits_meme_width_with_padding(self, _run, _duration, animate_meme, animate, tmp_path):
        image = tmp_path / "meme.jpg"
        image.write_bytes(b"jpg")
        voice = tmp_path / "voice.mp3"
        voice.write_bytes(b"mp3")
        timeline = [{
            "path": str(image),
            "duration_seconds": 4,
            "effect": "punch_zoom",
            "type": "meme",
            "source": "imgflip",
            "fit": "fit_width_pad",
            "fill_color": "#111111",
        }]

        assemble.assemble_video([], voice, tmp_path, "meme", timeline=timeline)

        animate.assert_not_called()
        animate_meme.assert_called_once()
        assert animate_meme.call_args.args[4] == "#111111"

    @patch("verticals.assemble.animate_frame")
    @patch("verticals.assemble.get_audio_duration", return_value=6.0)
    @patch("verticals.assemble.run_cmd", return_value=MagicMock(stdout=""))
    def test_concat_file_writes_explicit_segment_durations(self, _run, _duration, _animate, tmp_path):
        frames = []
        timeline = []
        for index, seconds in enumerate([2.0, 4.0]):
            image = tmp_path / f"f{index}.png"
            image.write_bytes(b"png")
            frames.append(image)
            timeline.append({"path": str(image), "duration_seconds": seconds, "source": "openai"})
        voice = tmp_path / "voice.mp3"
        voice.write_bytes(b"mp3")

        assemble.assemble_video(frames, voice, tmp_path, "durations", timeline=timeline)

        concat_text = (tmp_path / "concat.txt").read_text(encoding="utf-8")
        assert "duration 2.000" in concat_text
        assert "duration 4.000" in concat_text
        assert concat_text.strip().endswith("anim_1.mp4'")
        concat_commands = [
            call.args[0]
            for call in _run.call_args_list
            if "-filter_complex" in call.args[0]
        ]
        assert any("concat=n=2:v=1:a=0" in command[command.index("-filter_complex") + 1] for command in concat_commands)

    @patch("verticals.assemble.get_audio_duration", return_value=3.0)
    @patch("verticals.assemble.run_cmd", return_value=MagicMock(stdout=""))
    def test_harvested_video_uses_editor_source_offset(self, run, _duration, tmp_path):
        clip = tmp_path / "clip.mp4"
        clip.write_bytes(b"video")
        voice = tmp_path / "voice.mp3"
        voice.write_bytes(b"voice")
        timeline = [{
            "path": str(clip),
            "source": "youtube_harvest",
            "duration_seconds": 3.0,
            "source_start_seconds": 8.5,
        }]

        assemble.assemble_video([], voice, tmp_path, "offset", timeline=timeline)

        fit_commands = [call.args[0] for call in run.call_args_list if "-stream_loop" in call.args[0]]
        assert fit_commands
        command = fit_commands[0]
        assert command[command.index("-ss") + 1] == "8.5"
        assert command[command.index("-t") + 1] == "3.0"
