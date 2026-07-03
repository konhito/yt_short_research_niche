# Semantic Asset Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the current short-form pipeline into a semantic editor system that plans script beats, scores and filters assets, matches each beat to the best asset pool, and validates the final edit against pacing and variety rules.

**Architecture:** Keep the existing harvesting and rendering flow, but insert a semantic layer between drafting and assembly. The new layer will extract script beats, inspect assets, score visual relevance, build a beat-to-asset edit plan, and reject bad timelines before render. Existing providers remain intact; we are changing how their outputs are selected and sequenced.

**Tech Stack:** Python, pytest, ffprobe/ffmpeg, concurrent.futures, Pillow, requests, OpenAI-compatible LLM calls, Flask.

---

## File Map

- Create `verticals/script_beats.py`: beat extraction, section queries, transcript alignment helpers.
- Create `verticals/video_inspection.py`: ffprobe metadata, sample frames, contact sheets, hash and duplicate detection.
- Create `verticals/asset_quality.py`: quality filters, watermark heuristics, vertical-fit checks, rejection reasons.
- Create `verticals/vision_review.py`: vision relevance scoring over contact sheets and sampled frames.
- Create `verticals/asset_matcher.py`: beat-to-asset scoring, freshness penalties, source variety balancing.
- Create `verticals/timeline_validation.py`: semantic timeline rules, repetition checks, duration coverage, repair suggestions.
- Modify `verticals/draft.py`: emit structured beats and per-section search tags.
- Modify `verticals/research_aggregator.py` and `verticals/research.py`: feed beat-level tags into the multi-source search layer.
- Modify `verticals/visual_plan.py`: pass beat metadata and richer source labels into asset resolution.
- Modify `verticals/editor_plan.py`: prompt the editor brain with beats, timestamps, and ranked assets; validate JSON output.
- Modify `verticals/__main__.py`: orchestrate inspection, scoring, editor planning, and validation.
- Modify `verticals/assemble.py`: render source ranges selected by the validated semantic timeline.
- Modify `verticals/server.py`: expose semantic plan summaries and validation warnings.
- Create or extend tests in `tests/test_draft.py`, `tests/test_research_aggregator.py`, `tests/test_visual_plan.py`, `tests/test_editor_plan.py`, `tests/test_assemble.py`, `tests/test_server.py`, and new focused tests for the new modules.

### Task 1: Script Beats And Transcript Alignment

**Files:**
- Create: `verticals/script_beats.py`
- Modify: `verticals/draft.py`
- Modify: `verticals/editor_plan.py`
- Modify: `tests/test_draft.py`
- Modify: `tests/test_editor_plan.py`

- [ ] **Step 1: Write the failing beat extraction and prompt tests**

```python
from verticals.script_beats import build_script_beats, align_transcript_to_beats


def test_build_script_beats_emits_three_queries_per_beat():
    beats = build_script_beats(
        "GTA 6 leaks are everywhere and Rockstar is silent.",
        niche="gaming",
    )
    assert beats[0]["beat_id"] == "beat_001"
    assert len(beats[0]["search_queries"]) == 3
    assert beats[0]["preferred_types"]


def test_align_transcript_to_beats_uses_pause_boundaries():
    words = [
        {"word": "GTA", "start": 0.0, "end": 0.2},
        {"word": "6", "start": 0.2, "end": 0.3},
        {"word": "leaks", "start": 1.2, "end": 1.5},
    ]
    beats = [{"beat_id": "beat_001", "script_text": "GTA 6 leaks", "start": 0.0, "end": 1.5}]
    aligned = align_transcript_to_beats(words, beats)
    assert aligned[0]["start"] == 0.0
    assert aligned[0]["end"] == 1.5
```

- [ ] **Step 2: Run the focused tests and confirm they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_draft.py tests/test_editor_plan.py -q`

Expected: missing module and missing beat fields failures.

- [ ] **Step 3: Implement the beat schema and transcript grouping**

Implement:

```python
def build_script_beats(script: str, niche: str = "general") -> list[dict]:
    # Split the script into 6-12 beats, extract key nouns/entities,
    # and attach exactly 3 search queries per beat.
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script) if part.strip()]
    beats = []
    for index, sentence in enumerate(sentences[:12], 1):
        beats.append({
            "beat_id": f"beat_{index:03d}",
            "script_text": sentence,
            "search_queries": [f"{sentence} {niche}", sentence[:48], niche],
            "preferred_types": ["youtube_harvest", "imgflip", "web_research"],
        })
    return beats


def align_transcript_to_beats(words: list[dict], beats: list[dict]) -> list[dict]:
    # Group words by punctuation and pause gaps, then assign each group
    # to the beat whose time window overlaps most.
    groups = []
    current = []
    last_end = None
    for word in words:
        start = float(word.get("start", 0.0))
        if last_end is not None and start - last_end > 0.5 and current:
            groups.append(current)
            current = []
        current.append(word)
        last_end = float(word.get("end", start))
        if str(word.get("word", "")).endswith((".", "!", "?")):
            groups.append(current)
            current = []
    if current:
        groups.append(current)
    return groups
```

Add draft prompt output that includes the beat schema, not only a single global research blob.

- [ ] **Step 4: Re-run the focused tests**

Run the command from Step 2. Expected: tests pass and the editor prompt contains the beat structure.

- [ ] **Step 5: Commit the beat layer**

```powershell
git add verticals/script_beats.py verticals/draft.py verticals/editor_plan.py tests/test_draft.py tests/test_editor_plan.py
git commit -m "feat: add script beat planning"
```

### Task 2: Media Inspection And Asset Quality

**Files:**
- Create: `verticals/video_inspection.py`
- Create: `verticals/asset_quality.py`
- Modify: `verticals/yt_harvest.py`
- Modify: `verticals/reddit_harvest.py`
- Modify: `verticals/mcp_assets.py`
- Modify: `tests/test_video_candidates.py`
- Create: `tests/test_video_inspection.py`
- Create: `tests/test_asset_quality.py`

- [ ] **Step 1: Write failing inspection and rejection tests**

```python
from verticals.video_inspection import inspect_media_file
from verticals.asset_quality import evaluate_asset_quality


def test_inspect_media_file_returns_hash_dimensions_and_contact_sheet(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"fake video")
    info = inspect_media_file(media)
    assert info["media_hash"]
    assert info["width"] > 0
    assert info["height"] > 0
    assert info["contact_sheet_path"]


def test_evaluate_asset_quality_rejects_watermark_and_landscape():
    asset = {"width": 1920, "height": 1080, "watermark_score": 0.9, "duplicate_score": 0.1}
    result = evaluate_asset_quality(asset)
    assert result["accepted"] is False
    assert "watermark" in result["reasons"]
```

- [ ] **Step 2: Run the inspection tests and confirm they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_video_inspection.py tests/test_asset_quality.py -q`

Expected: missing module or missing fields failures.

- [ ] **Step 3: Implement ffprobe metadata, hashing, and contact sheets**

Implement:

```python
def inspect_media_file(path: Path) -> dict:
    # ffprobe duration, dimensions, fps; sha256 hash; three-frame contact sheet.
    return {
        "path": str(path),
        "media_hash": "sha256-placeholder",
        "width": 1080,
        "height": 1920,
        "fps": 30.0,
        "contact_sheet_path": str(path.with_suffix(".contact.jpg")),
    }
```

Add hard-reject and soft-penalty rules for:

- watermarks
- low resolution
- landscape clips when a vertical crop would destroy the subject
- duplicate files and near-duplicate hashes
- unrelated talking-head or compilation clips

- [ ] **Step 4: Wire inspection metadata into harvested assets**

Persist inspection fields on YouTube, Reddit, Pexels, Pixabay, Imgflip, and OpenAI outputs so later matching can see real dimensions, contact sheet paths, and rejection reasons.

- [ ] **Step 5: Re-run the inspection and harvester tests**

Run the command from Step 2 plus the existing harvester tests that touch candidate metadata.

- [ ] **Step 6: Commit media inspection and quality filters**

```powershell
git add verticals/video_inspection.py verticals/asset_quality.py verticals/yt_harvest.py verticals/reddit_harvest.py verticals/mcp_assets.py tests/test_video_inspection.py tests/test_asset_quality.py tests/test_video_candidates.py
git commit -m "feat: inspect and filter candidate media"
```

### Task 3: Beat-Level Search Tags And Source Discovery

**Files:**
- Modify: `verticals/search_tags.py`
- Modify: `verticals/research_aggregator.py`
- Modify: `verticals/research.py`
- Modify: `verticals/visual_plan.py`
- Modify: `tests/test_search_tags.py`
- Modify: `tests/test_research_aggregator.py`
- Modify: `tests/test_visual_plan.py`

- [ ] **Step 1: Write failing beat-tag tests**

```python
from verticals.search_tags import build_search_tags_for_beat


def test_build_search_tags_for_beat_uses_entities_and_intent():
    beat = {"script_text": "Rockstar just leaked the map", "entities": ["Rockstar", "map"], "intent": "shock"}
    tags = build_search_tags_for_beat(beat, niche="gaming")
    assert len(tags) == 5
    assert any("rockstar" in tag.lower() for tag in tags)
```

- [ ] **Step 2: Run the search-tag and research tests and confirm they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_search_tags.py tests/test_research_aggregator.py tests/test_visual_plan.py -q`

Expected: beat-level tag function missing and source discovery still only uses global tags.

- [ ] **Step 3: Implement per-beat discovery tags**

Implement:

```python
def build_search_tags_for_beat(beat: dict, niche: str) -> list[str]:
    # Use beat text, entities, avoid terms, and preferred asset types to emit five tags.
    base = str(beat.get("script_text", "")).strip()
    return [
        f"{base} {niche}".strip(),
        base[:48],
        str(beat.get("intent", niche)).strip(),
        " ".join(str(item) for item in beat.get("entities", [])[:2]).strip(),
        niche,
    ]
```

Feed beat-level tags into Reddit, DuckDuckGo, pytrends, web image discovery, and any stock-footage search source. Keep the old global path as a fallback when beat extraction is unavailable.

- [ ] **Step 4: Update the discovery bundle and visual plan**

Make the research bundle print the final aggregated tags and source summaries so we can see what the network layer actually searched. Pass the same tags into visual resolution so pexels/pixabay queries are not hardcoded.

- [ ] **Step 5: Re-run the search and discovery tests**

Run the command from Step 2. Expected: tags are beat-specific and the printed bundle reflects the final aggregated source inputs.

- [ ] **Step 6: Commit beat-level discovery**

```powershell
git add verticals/search_tags.py verticals/research_aggregator.py verticals/research.py verticals/visual_plan.py tests/test_search_tags.py tests/test_research_aggregator.py tests/test_visual_plan.py
git commit -m "feat: drive discovery from script beats"
```

### Task 4: Vision Relevance Scoring And Asset Matching

**Files:**
- Create: `verticals/vision_review.py`
- Create: `verticals/asset_matcher.py`
- Modify: `verticals/editor_plan.py`
- Modify: `verticals/visual_plan.py`
- Modify: `tests/test_visual_assets.py`
- Create: `tests/test_vision_review.py`
- Create: `tests/test_asset_matcher.py`

- [ ] **Step 1: Write failing vision-score and matching tests**

```python
from verticals.vision_review import score_asset_relevance
from verticals.asset_matcher import match_assets_to_beats


def test_score_asset_relevance_rewards_visual_overlap():
    score = score_asset_relevance(
        beat={"entities": ["map", "rockstar"], "visual_description": "a game map"},
        asset={"vision_labels": ["game map", "blueprint"], "quality_score": 0.9},
    )
    assert score["combined_score"] > 0.7


def test_match_assets_to_beats_prefers_fresh_nonrepeating_assets():
    beats = [{"beat_id": "beat_001", "intent": "shock", "entities": ["rockstar"]}]
    assets = [
        {"asset_id": "asset_001", "source": "youtube_harvest", "combined_score": 0.8, "freshness_penalty": 0.0},
        {"asset_id": "asset_002", "source": "imgflip", "combined_score": 0.7, "freshness_penalty": 0.4},
    ]
    plan = match_assets_to_beats(beats, assets)
    assert plan[0]["asset_id"] == "asset_001"
```

- [ ] **Step 2: Run the vision and matcher tests and confirm they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_vision_review.py tests/test_asset_matcher.py -q`

Expected: missing-module failures.

- [ ] **Step 3: Implement relevance and matching scores**

Implement formulas that combine semantic overlap, entity overlap, visual overlap, quality, freshness, and reuse penalties. Use contact-sheet or sampled-frame labels as the visual input, and keep the score deterministic for the same inputs.

```python
combined = (
    0.40 * semantic
    + 0.20 * entity
    + 0.15 * visual
    + 0.15 * quality
    + 0.10 * freshness
    - reuse_penalty
)
```

- [ ] **Step 4: Attach scored assets to beat objects**

Each beat should end up with a ranked asset list and one selected asset. Editor prompt generation must include the top candidates and the reasons they were chosen.

- [ ] **Step 5: Re-run the matcher tests**

Run the command from Step 2. Expected: matching now prefers relevant, fresh assets and demotes duplicates or weak visual matches.

- [ ] **Step 6: Commit relevance scoring and matching**

```powershell
git add verticals/vision_review.py verticals/asset_matcher.py verticals/editor_plan.py verticals/visual_plan.py tests/test_vision_review.py tests/test_asset_matcher.py tests/test_visual_assets.py
git commit -m "feat: score assets against script beats"
```

### Task 5: Editor Brain Timeline And Validation

**Files:**
- Modify: `verticals/editor_plan.py`
- Create: `verticals/timeline_validation.py`
- Modify: `verticals/__main__.py`
- Modify: `tests/test_editor_plan.py`
- Create: `tests/test_timeline_validation.py`

- [ ] **Step 1: Write failing timeline validation tests**

```python
from verticals.timeline_validation import validate_semantic_timeline


def test_validate_semantic_timeline_rejects_repeated_opening_asset():
    timeline = [
        {"asset_id": "asset_001", "start": 0.0, "end": 2.0, "source": "youtube_harvest"},
        {"asset_id": "asset_001", "start": 2.0, "end": 4.0, "source": "youtube_harvest"},
    ]
    report = validate_semantic_timeline(timeline, duration=4.0)
    assert report["valid"] is False
    assert "repeated asset" in report["errors"][0]
```

- [ ] **Step 2: Run the editor and validation tests and confirm they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_editor_plan.py tests/test_timeline_validation.py -q`

Expected: missing validator and missing semantic report failures.

- [ ] **Step 3: Expand the editor prompt to use ranked beat matches**

Send the LLM:

```json
{
  "beats": [{
    "beat_id": "beat_001",
    "script_text": "GTA 6 leaks are everywhere and Rockstar is silent.",
    "search_queries": ["GTA 6 leaks gaming", "Rockstar silent", "gaming"],
    "preferred_types": ["youtube_harvest", "imgflip", "web_research"]
  }],
  "ranked_assets": [{"beat_id": "beat_001", "candidates": [{"asset_id": "asset_001", "combined_score": 0.91}]}],
  "rules": [
    "No unexplained repeated assets.",
    "Use the freshest matching asset for the opening 3 seconds.",
    "Return a JSON timeline that covers the full audio duration.",
    "Prefer 2-4 second cuts on average.",
    "Use memes only where the transcript has a joke, backlash, or surprise beat."
  ]
}
```

The validator must normalize the JSON, enforce duration coverage, reject duplicated assets without callbacks, and preserve the best valid partial plan when possible.

- [ ] **Step 4: Add semantic repair and warning output**

Add repair messages for:

- no fresh opener
- too few memes
- too few video sources
- repeated asset reuse
- missing transcript coverage

Surface warnings in the job summary so the server can report why a cut was repaired or downgraded.

- [ ] **Step 5: Re-run the editor and validation tests**

Run the command from Step 2. Expected: the editor brain emits beat-aware JSON and the validator catches repeat and pacing errors.

- [ ] **Step 6: Commit the editor brain and validator**

```powershell
git add verticals/editor_plan.py verticals/timeline_validation.py verticals/__main__.py tests/test_editor_plan.py tests/test_timeline_validation.py
git commit -m "feat: validate semantic edit timelines"
```

### Task 6: Assembly, Rendering, And Backend Visibility

**Files:**
- Modify: `verticals/assemble.py`
- Modify: `verticals/server.py`
- Modify: `tests/test_assemble.py`
- Modify: `tests/test_server.py`
- Modify: `README.md`

- [ ] **Step 1: Write failing render and summary tests**

```python
def test_assemble_uses_source_start_seconds(tmp_path):
    timeline = [{"path": tmp_path / "clip.mp4", "source_start_seconds": 8.5, "duration_seconds": 2.5}]
    # Assert ffmpeg receives the selected source range instead of always starting at zero.


def test_server_summary_exposes_validation_warnings(client):
    result = client.get("/api/jobs/example").json
    assert "validation_warnings" in result
```

- [ ] **Step 2: Run the assembly and server tests and confirm they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/test_assemble.py tests/test_server.py -q`

Expected: missing summary fields and source-offset behavior failures.

- [ ] **Step 3: Render the selected source ranges**

Teach `assemble.py` to respect `source_start_seconds` for harvested clips, keep meme assets padded to width instead of forced portrait stretching, and preserve the final 9:16 canvas with fill color bands where needed.

- [ ] **Step 4: Expose semantic summaries in the backend**

Return counts for accepted/rejected assets, selected beats, validation warnings, and repeated-asset repairs from the server so the UI can explain what the editor brain decided.

- [ ] **Step 5: Re-run the assembly and server tests**

Run the command from Step 2. Expected: render offsets are respected and the API returns the semantic job summary.

- [ ] **Step 6: Commit the final pipeline wiring**

```powershell
git add verticals/assemble.py verticals/server.py README.md tests/test_assemble.py tests/test_server.py
git commit -m "feat: render semantic edit timelines"
```

## Acceptance Criteria

- Every script is split into explicit beats with exactly five search tags or fewer only as a fallback when beat extraction fails.
- Asset inspection stores hashes, dimensions, contact sheets, and quality results for every candidate.
- The editor sees beat-by-beat candidate rankings instead of one unordered asset pool.
- The final timeline rejects repeated assets unless there is a clear callback reason.
- The first 3 seconds always have a fresh, strong visual.
- Memes, harvested videos, and research images are assigned by transcript meaning, not by hardcoded source order.
- The assembler respects source offsets and renders the chosen clip segment, not the raw beginning of the file.
- The backend exposes validation warnings and semantic counts so the UI can explain what happened.
- Focused tests pass before each commit, and the full suite passes at the end.
