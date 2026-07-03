from unittest.mock import patch

from PIL import Image

from verticals.broll import animate_frame, generate_broll


@patch("verticals.broll.get_openai_key", return_value="key")
@patch("verticals.broll.generate_openai_image")
def test_openai_broll_requests_portrait_image(mock_generate, _mock_key, tmp_path):
    def create(prompt, output_path, api_key, **kwargs):
        Image.new("RGB", (1024, 1536)).save(output_path)
        return output_path

    mock_generate.side_effect = create
    paths = generate_broll(["game scene"], tmp_path)
    assert mock_generate.call_args.kwargs["size"] == "1024x1536"
    assert "safe area" in mock_generate.call_args.args[0].lower()
    assert Image.open(paths[0]).size == (1080, 1920)


@patch("verticals.broll.run_cmd")
def test_punch_zoom_and_shake_use_distinct_filters(mock_run, tmp_path):
    animate_frame(tmp_path / "in.png", tmp_path / "punch.mp4", 2, "punch_zoom")
    punch = mock_run.call_args.args[0]
    animate_frame(tmp_path / "in.png", tmp_path / "shake.mp4", 2, "shake")
    shake = mock_run.call_args.args[0]
    assert "zoompan" in punch[punch.index("-vf") + 1]
    assert "sin(" in shake[shake.index("-vf") + 1]
