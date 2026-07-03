from verticals.thumbnail import _build_thumbnail_prompt


def test_thumbnail_prompt_includes_all_profile_constraints():
    prompt = _build_thumbnail_prompt(
        "GTA character",
        {
            "style": "dark high energy",
            "text_color": "#FFFFFF",
            "accent_color": "#FF4444",
            "text_position": "center_or_left",
            "max_words": 4,
            "font_style": "bold impact",
            "guidelines": ["Show a character", "No generic imagery"],
        },
    )
    assert "#FF4444" in prompt
    assert "maximum 4 words" in prompt.lower()
    assert "bold impact" in prompt
    assert "Show a character" in prompt
