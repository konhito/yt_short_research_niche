"""Tests for CLI behavior in verticals.__main__."""

from types import SimpleNamespace

from verticals import __main__ as cli


def test_cmd_run_skips_upload_when_youtube_token_missing(monkeypatch, capsys):
    draft_path = "C:/tmp/draft.json"
    video_path = "C:/tmp/video.mp4"

    monkeypatch.setattr(cli, "cmd_draft", lambda args: draft_path)
    monkeypatch.setattr(cli, "cmd_produce", lambda args: video_path)

    def _raise_missing_token(args):
        raise FileNotFoundError("YouTube OAuth token not found")

    monkeypatch.setattr(cli, "cmd_upload", _raise_missing_token)

    result = cli.cmd_run(SimpleNamespace(dry_run=False, lang="en", voice="edge"))
    output = capsys.readouterr().out

    assert result == video_path
    assert "Upload skipped" in output
    assert "Video ready" in output
