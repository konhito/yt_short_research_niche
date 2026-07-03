# Niche Profile Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect every supported niche YAML setting to research, drafting, voice, captions, music, and thumbnail production while preserving explicit request overrides.

**Architecture:** `verticals/niche.py` normalizes raw YAML into stage-specific dictionaries. Consumers receive only their normalized configuration, with explicit CLI/API values applied after niche defaults. Existing hardcoded behavior remains fallback behavior for old or partial profiles.

**Tech Stack:** Python 3.11+, PyYAML, Flask, pytest, feedparser, pytrends, Edge TTS, OpenAI image generation, ffmpeg ASS subtitles.

---

### Task 1: Normalize Niche Configuration

**Files:**
- Modify: `verticals/niche.py`
- Modify: `tests/test_niche.py`

- [ ] **Step 1: Write failing tests for aliases and normalized defaults**

```python
from verticals.niche import get_voice_config, get_caption_config, get_discovery_config


def test_edge_alias_uses_edge_tts_profile_voice():
    profile = {"voice": {"suggested_voices": {"edge_tts": {"en": "gaming-voice"}}}}
    assert get_voice_config(profile, provider="edge", lang="en")["voice_id"] == "gaming-voice"


def test_discovery_config_returns_isolated_defaults():
    config = get_discovery_config({})
    assert config == {
        "reddit": {"subreddits": []},
        "rss": {"feeds": []},
        "google_trends": {"category": "", "geo": "US"},
        "youtube_trending": {"category_id": ""},
    }


def test_caption_config_preserves_all_style_fields():
    config = get_caption_config({"captions": {"position": "center", "background": "none"}})
    assert config["position"] == "center"
    assert config["background"] == "none"
```

- [ ] **Step 2: Run tests and verify red**

Run: `.venv\Scripts\python.exe -m pytest tests/test_niche.py -v`

Expected: alias and discovery-default assertions fail.

- [ ] **Step 3: Implement provider normalization and discovery defaults**

Add a provider alias map in `verticals/niche.py`, normalize `edge` to
`edge_tts` in `get_voice_config`, and make `get_discovery_config` merge each
nested profile section into fresh defaults rather than returning raw YAML.

- [ ] **Step 4: Run tests and verify green**

Run: `.venv\Scripts\python.exe -m pytest tests/test_niche.py -v`

Expected: all niche tests pass.

### Task 2: Connect Profile Discovery Sources

**Files:**
- Modify: `verticals/research.py`
- Modify: `verticals/research_aggregator.py`
- Modify: `tests/test_research_aggregator.py`

- [ ] **Step 1: Write failing tests for discovery propagation**

```python
def test_research_topic_passes_profile_discovery(monkeypatch):
    captured = {}
    monkeypatch.setattr("verticals.research.load_niche", lambda name: {
        "discovery": {"reddit": {"subreddits": ["Games"]}, "rss": {"feeds": ["https://example.test/feed"]}}
    })

    class FakeAgg:
        def __init__(self, topic, niche="general", geo="US", discovery=None):
            captured["discovery"] = discovery
        def gather(self, limit=8):
            return []
        def format_bundle(self, items):
            return "bundle"

    monkeypatch.setattr("verticals.research.ResearchAggregator", FakeAgg)
    research_topic("gta", niche="gaming")
    assert captured["discovery"]["reddit"]["subreddits"] == ["Games"]


def test_aggregator_uses_configured_subreddits(monkeypatch):
    agg = ResearchAggregator("gta", niche="gaming", discovery={"reddit": {"subreddits": ["Games"]}})
    seen = []
    monkeypatch.setattr(agg, "_search_subreddit", lambda subreddit, limit: seen.append(subreddit) or [])
    agg.fetch_reddit(limit=2)
    assert seen == ["Games"]
```

Add equivalent focused tests for configured RSS feeds and Trends geo/category.
YouTube category configuration is retained in normalized discovery and logged as
unavailable until a YouTube discovery adapter is configured; it must not trigger
an unauthenticated API call.

- [ ] **Step 2: Run tests and verify red**

Run: `.venv\Scripts\python.exe -m pytest tests/test_research_aggregator.py -v`

Expected: constructor rejects `discovery` or configured sources are ignored.

- [ ] **Step 3: Implement discovery injection and per-source gathering**

Load normalized discovery in `research_topic`, pass it to `ResearchAggregator`,
use configured subreddits before `NICHE_TO_SUBREDDITS`, parse configured RSS
feeds into `ResearchItem(source="rss", ...)`, and pass configured Trends values
to pytrends. Isolate and log failures per source.

- [ ] **Step 4: Run tests and verify green**

Run: `.venv\Scripts\python.exe -m pytest tests/test_research_aggregator.py -v`

Expected: all research tests pass.

### Task 3: Complete Draft Visual And Thumbnail Guidance

**Files:**
- Modify: `verticals/draft.py`
- Modify: `tests/test_draft.py`

- [ ] **Step 1: Write a failing prompt-capture test**

```python
def test_draft_prompt_contains_palette_and_thumbnail_fields(monkeypatch):
    captured = {}
    monkeypatch.setattr("verticals.draft.research_topic", lambda *args, **kwargs: "research")
    monkeypatch.setattr("verticals.draft.load_niche", lambda name: {
        "name": "gaming",
        "script": {},
        "visuals": {"color_palette": ["#FFD700", "#FF4444"]},
        "thumbnail": {
            "text_color": "#FFFFFF", "accent_color": "#FF4444",
            "text_position": "center_or_left", "max_words": 4,
            "font_style": "bold impact",
        },
    })
    monkeypatch.setattr("verticals.draft.call_llm", lambda prompt, provider=None: captured.setdefault("prompt", prompt) or "{}")
    # Return valid draft JSON from the seam in the actual test.
    generate_draft("gta", niche="gaming", provider="openai")
    assert "#FFD700" in captured["prompt"]
    assert "Maximum thumbnail words: 4" in captured["prompt"]
```

- [ ] **Step 2: Run test and verify red**

Run: `.venv\Scripts\python.exe -m pytest tests/test_draft.py -v`

Expected: palette and full thumbnail fields are absent.

- [ ] **Step 3: Add complete guidance and suffix de-duplication**

Include palette, every supported thumbnail field, and all guidelines in the LLM
prompt. Append the visual suffix only when the generated prompt does not already
end with the same normalized suffix.

- [ ] **Step 4: Run tests and verify green**

Run: `.venv\Scripts\python.exe -m pytest tests/test_draft.py -v`

Expected: all draft tests pass.

### Task 4: Apply Full Caption Styling

**Files:**
- Modify: `verticals/captions.py`
- Modify: `verticals/__main__.py`
- Modify: `tests/test_captions.py`
- Modify: `tests/test_main.py`

- [ ] **Step 1: Write failing ASS style tests**

```python
def test_ass_applies_full_niche_style(sample_words, tmp_work_dir):
    output = tmp_work_dir / "styled.ass"
    _generate_ass(
        sample_words, output,
        highlight_color="#FFD700",
        text_color="#00BFFF",
        font_family="Impact",
        font_size=76,
        font_weight="bold",
        position="center",
        background="none",
        group_size=3,
    )
    content = output.read_text(encoding="utf-8")
    assert "Impact,76" in content
    assert "Alignment=5" not in content  # assert actual comma-delimited style alignment field
    assert "&H00FFBF00" in content
```

The actual test should assert the precise ASS style row fields: bold `-1`, center
alignment `5`, transparent border style `1`, normal text color, and highlighted
event color.

- [ ] **Step 2: Run tests and verify red**

Run: `.venv\Scripts\python.exe -m pytest tests/test_captions.py tests/test_main.py -v`

Expected: `_generate_ass` and `generate_captions` reject the new style arguments.

- [ ] **Step 3: Implement safe ASS style normalization**

Extend `generate_captions` and `_generate_ass` with text color, weight, position,
and background parameters. Convert CSS hex to ASS BGR; map `lower_third` to
alignment `2`, `center` to `5`; map bold to `-1`; map `semi_transparent_dark` to
border style `3` and `none` to border style `1`. Pass all normalized caption
fields from `cmd_produce`.

- [ ] **Step 4: Run tests and verify green**

Run: `.venv\Scripts\python.exe -m pytest tests/test_captions.py tests/test_main.py -v`

Expected: all caption and production wiring tests pass.

### Task 5: Select Music By Niche Tags

**Files:**
- Modify: `verticals/music.py`
- Modify: `tests/test_music.py`

- [ ] **Step 1: Write failing ranking tests**

```python
def test_rank_tracks_prefers_filename_tag_matches(tmp_path):
    tracks = [tmp_path / "calm-piano.mp3", tmp_path / "gaming-hype-bass.mp3"]
    ranked = _rank_tracks(tracks, ["gaming", "hype", "bass"])
    assert ranked == [tracks[1]]


def test_rank_tracks_falls_back_to_all_tracks(tmp_path):
    tracks = [tmp_path / "one.mp3", tmp_path / "two.mp3"]
    assert _rank_tracks(tracks, ["unmatched"]) == tracks
```

- [ ] **Step 2: Run tests and verify red**

Run: `.venv\Scripts\python.exe -m pytest tests/test_music.py -v`

Expected: `_rank_tracks` cannot be imported.

- [ ] **Step 3: Implement deterministic ranking group and random variation**

Create `_rank_tracks` that tokenizes lowercase filename stems, scores exact tag
matches, and returns every track tied for the highest positive score or all
tracks when no score is positive. Call `random.choice` on that candidate group.

- [ ] **Step 4: Run tests and verify green**

Run: `.venv\Scripts\python.exe -m pytest tests/test_music.py -v`

Expected: all music tests pass.

### Task 6: Preserve Thumbnail Configuration At Generation

**Files:**
- Modify: `verticals/thumbnail.py`
- Modify: `verticals/__main__.py`
- Create: `tests/test_thumbnail.py`

- [ ] **Step 1: Write a failing final-prompt test**

```python
def test_thumbnail_prompt_includes_profile_constraints(monkeypatch, tmp_path):
    captured = {}
    monkeypatch.setattr("verticals.thumbnail.generate_openai_image", lambda prompt, output: captured.setdefault("prompt", prompt) or output)
    draft = {"thumbnail_prompt": "GTA character", "youtube_title": "Leak", "niche": "gaming"}
    config = {"accent_color": "#FF4444", "max_words": 4, "font_style": "bold impact"}
    generate_thumbnail(draft, tmp_path, profile_config=config)
    assert "#FF4444" in captured["prompt"]
    assert "4 words" in captured["prompt"]
```

- [ ] **Step 2: Run test and verify red**

Run: `.venv\Scripts\python.exe -m pytest tests/test_thumbnail.py -v`

Expected: `generate_thumbnail` rejects `profile_config`.

- [ ] **Step 3: Append normalized thumbnail constraints and wire upload path**

Add optional `profile_config` to `generate_thumbnail`, append supported fields
to the final provider prompt, and pass `get_thumbnail_config(load_niche(...))`
from `cmd_upload`. Explicit draft prompt content remains first and is never
discarded.

- [ ] **Step 4: Run tests and verify green**

Run: `.venv\Scripts\python.exe -m pytest tests/test_thumbnail.py tests/test_main.py -v`

Expected: thumbnail and upload wiring tests pass.

### Task 7: Full Regression Verification

**Files:**
- Modify only files required by failures caused by this feature.

- [ ] **Step 1: Run focused integration tests**

Run: `.venv\Scripts\python.exe -m pytest tests/test_niche.py tests/test_research_aggregator.py tests/test_draft.py tests/test_captions.py tests/test_music.py tests/test_thumbnail.py tests/test_main.py -v`

Expected: all focused tests pass.

- [ ] **Step 2: Run the full suite**

Run: `.venv\Scripts\python.exe -m pytest -q`

Expected: all tests pass with no new warnings or errors.

- [ ] **Step 3: Check the final diff**

Run: `git diff --check`

Expected: no whitespace errors. Confirm existing unrelated worktree changes were
not reverted or overwritten.

