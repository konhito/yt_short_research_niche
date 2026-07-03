"""Tests for pipeline/draft.py — draft generation with mocked Claude API."""

import json
from unittest.mock import patch, MagicMock

from verticals.draft import generate_draft


class TestGenerateDraft:
    @patch("verticals.draft.research_topic", return_value="research")
    @patch("verticals.draft._call_claude")
    def test_includes_palette_and_complete_thumbnail_guidance(self, mock_claude, _mock_research):
        mock_claude.return_value = json.dumps({
            "script": "s", "broll_prompts": ["p1"], "youtube_title": "T",
            "youtube_description": "D", "youtube_tags": "t", "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })
        generate_draft("GTA", niche="gaming")
        prompt = mock_claude.call_args[0][0]
        assert "#FFD700" in prompt
        assert "Thumbnail text color: #FFFFFF" in prompt
        assert "Thumbnail accent color: #FF4444" in prompt
        assert "Maximum thumbnail words: 4" in prompt
        assert "Thumbnail font style: bold impact style" in prompt
        assert "6 to 10 meme" in prompt
        assert "2 to 4 Pexels" in prompt
        assert "visual_plan" in prompt
        assert '"search_tags"' in prompt

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft._call_claude")
    def test_basic_draft_generation(self, mock_claude, mock_research):
        mock_research.return_value = "Some research data about the topic."
        mock_claude.return_value = json.dumps({
            "script": "This is a test script about AI.",
            "broll_prompts": ["Prompt 1", "Prompt 2", "Prompt 3"],
            "youtube_title": "AI Revolution 2026",
            "youtube_description": "All about AI.",
            "youtube_tags": "ai,tech,2026",
            "instagram_caption": "AI is changing the world!",
            "thumbnail_prompt": "Futuristic AI image",
        })

        draft = generate_draft("AI is changing everything in 2026")

        assert draft["script"] == "This is a test script about AI."
        assert len(draft["broll_prompts"]) == 3
        assert draft["youtube_title"] == "AI Revolution 2026"
        assert draft["news"] == "AI is changing everything in 2026"
        assert draft["research"] == "Some research data about the topic."

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft._call_claude")
    def test_handles_code_block_wrapper(self, mock_claude, mock_research):
        mock_research.return_value = "research"
        mock_claude.return_value = '```json\n{"script":"test","broll_prompts":["p1","p2","p3"],"youtube_title":"T","youtube_description":"D","youtube_tags":"t","instagram_caption":"C","thumbnail_prompt":"P"}\n```'

        draft = generate_draft("Test topic")
        assert draft["script"] == "test"

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft._call_claude")
    def test_sanitizes_non_string_fields(self, mock_claude, mock_research):
        mock_research.return_value = "research"
        mock_claude.return_value = json.dumps({
            "script": 12345,  # non-string
            "broll_prompts": "not a list",  # non-list
            "youtube_title": "T",
            "youtube_description": "D",
            "youtube_tags": "t",
            "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })

        draft = generate_draft("Test")
        assert isinstance(draft["script"], str)
        assert isinstance(draft["broll_prompts"], list)
        assert len(draft["broll_prompts"]) == 3  # fallback

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft._call_claude")
    def test_includes_channel_context(self, mock_claude, mock_research):
        mock_research.return_value = "research"
        mock_claude.return_value = json.dumps({
            "script": "s", "broll_prompts": ["p1", "p2", "p3"],
            "youtube_title": "T", "youtube_description": "D",
            "youtube_tags": "t", "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })

        draft = generate_draft("Test", channel_context="esports news channel")
        # Verify the channel context was passed to Claude
        call_args = mock_claude.call_args[0][0]
        assert "esports news channel" in call_args

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft._call_claude")
    def test_truncates_broll_prompts(self, mock_claude, mock_research):
        mock_research.return_value = "research"
        mock_claude.return_value = json.dumps({
            "script": "s",
            "broll_prompts": ["p1", "p2", "p3", "p4", "p5"],  # too many
            "youtube_title": "T", "youtube_description": "D",
            "youtube_tags": "t", "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })

        draft = generate_draft("Test")
        assert len(draft["broll_prompts"]) == 3  # truncated to 3

    @patch("verticals.draft.research_topic")
    @patch("verticals.draft._call_claude")
    def test_includes_script_beats_in_prompt_and_draft(self, mock_claude, mock_research):
        mock_research.return_value = "research"
        mock_claude.return_value = json.dumps({
            "script": "GTA 6 leaks are everywhere. Rockstar is silent.",
            "broll_prompts": ["p1", "p2", "p3"],
            "youtube_title": "T",
            "youtube_description": "D",
            "youtube_tags": "t",
            "instagram_caption": "C",
            "thumbnail_prompt": "P",
        })

        draft = generate_draft("GTA 6 leaks are everywhere. Rockstar is silent.", niche="gaming")

        prompt = mock_claude.call_args[0][0]
        assert "script_beats" in prompt
        assert draft["script_beats"][0]["beat_id"] == "beat_001"
        assert len(draft["script_beats"][0]["search_queries"]) == 3
