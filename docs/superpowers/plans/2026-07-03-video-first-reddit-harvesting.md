# Video-First Reddit Harvesting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make licensed YouTube Shorts and Reddit videos the primary gaming visuals, generate OpenAI images only when the harvested video pool is insufficient, and give the editor enough transcript and clip metadata to place each asset accurately.

**Architecture:** Add a PullPush discovery/downloader beside the existing YouTube harvester, normalize both into one candidate schema, deduplicate them, and harvest both sources concurrently. The production orchestrator will resolve harvested video, memes, stock footage, and fallback AI images in parallel, then pass timed transcript segments plus rich candidate metadata to the editor brain.

**Tech Stack:** Python 3.12, requests, yt-dlp, ffmpeg/imageio-ffmpeg, concurrent.futures, OpenAI-compatible LLM abstraction, pytest.

---

## File Map

- Create `verticals/reddit_harvest.py`: PullPush search, scoring, Reddit URL resolution, yt-dlp download, manifest persistence.
- Create `verticals/video_candidates.py`: shared candidate schema, URL/content deduplication, source balancing, relevance helpers.
- Modify `verticals/yt_harvest.py`: emit the shared schema and expose metadata-search/download phases separately.
- Modify `verticals/visual_plan.py`: parallel source resolution and conditional AI-image planning.
- Modify `verticals/editor_plan.py`: send timed transcript segments, clip labels, source URLs, and source-balance requirements.
- Modify `verticals/__main__.py`: run Reddit, YouTube, and other independent asset tasks concurrently.
- Modify `verticals/niche.py` and `niches/gaming.yaml`: define video-first thresholds and source targets.
- Modify `verticals/server.py`: expose source counts, rejected counts, and manifest paths in job results.
- Modify `README.md` and `.env.example`: document PullPush/Reddit and harvesting controls.
- Create `tests/test_reddit_harvest.py` and `tests/test_video_candidates.py`; extend existing harvester/editor/main tests.

### Task 1: Shared Candidate Model and Deduplication

**Files:**
- Create: `verticals/video_candidates.py`
- Create: `tests/test_video_candidates.py`

- [ ] **Step 1: Write failing candidate normalization tests**

```python
from verticals.video_candidates import deduplicate_candidates, normalize_candidate


def test_normalize_candidate_keeps_editor_metadata():
    item = normalize_candidate({
        "source": "reddit",
        "source_id": "abc",
        "title": "GTA 6 leak reaction",
        "url": "https://reddit.com/r/gaming/comments/abc/post",
        "media_url": "https://v.redd.it/xyz",
        "duration": 31,
        "relevance_score": 24,
    })
    assert item["type"] == "harvested_video"
    assert item["status"] == "candidate"
    assert item["protected"] is True


def test_deduplicate_candidates_prefers_higher_score():
    candidates = [
        {"url": "https://example.com/a", "media_hash": "same", "relevance_score": 10},
        {"url": "https://example.com/b", "media_hash": "same", "relevance_score": 20},
    ]
    assert deduplicate_candidates(candidates)[0]["url"].endswith("/b")
```

- [ ] **Step 2: Run tests and verify missing-module failure**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_video_candidates.py -q
```

Expected: collection fails because `verticals.video_candidates` does not exist.

- [ ] **Step 3: Implement normalization and deduplication**

Implement:

```python
def normalize_candidate(raw: dict) -> dict:
    return {
        **raw,
        "type": "harvested_video",
        "status": "candidate",
        "protected": True,
        "asset_role": "harvested_video",
        "effect": raw.get("effect", "hard_cut"),
        "fit": raw.get("fit", "cover_crop"),
    }


def deduplicate_candidates(items: list[dict]) -> list[dict]:
    best: dict[str, dict] = {}
    for item in items:
        key = item.get("media_hash") or item.get("media_url") or item.get("url")
        current = best.get(key)
        if current is None or item.get("relevance_score", 0) > current.get("relevance_score", 0):
            best[key] = item
    return sorted(best.values(), key=lambda item: item.get("relevance_score", 0), reverse=True)
```

- [ ] **Step 4: Verify shared candidate tests pass**

Run the command from Step 2. Expected: all tests pass.

- [ ] **Step 5: Commit the shared model**

```powershell
git add verticals/video_candidates.py tests/test_video_candidates.py
git commit -m "feat: add harvested video candidate model"
```

### Task 2: PullPush Reddit Video Discovery

**Files:**
- Create: `verticals/reddit_harvest.py`
- Create: `tests/test_reddit_harvest.py`

- [ ] **Step 1: Write failing PullPush request and scoring tests**

```python
from verticals.reddit_harvest import build_reddit_queries, search_reddit_videos


def test_build_reddit_queries_uses_draft_entities():
    draft = {"youtube_title": "GTA 6 Rockstar Leak Backlash", "script": "Fans are angry at Rockstar."}
    queries = build_reddit_queries(draft, "gaming")
    assert "GTA 6 Rockstar" in queries[0]


def test_search_reddit_videos_uses_video_filters(monkeypatch):
    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    captured = {}
    monkeypatch.setattr("verticals.reddit_harvest.requests.get", lambda url, **kwargs: captured.update(url=url, kwargs=kwargs) or FakeResponse({"data": []}))
    search_reddit_videos("GTA 6", ["gaming"], size=25)
    assert captured["kwargs"]["params"]["is_video"] == "true"
    assert captured["kwargs"]["params"]["over_18"] == "false"
    assert captured["kwargs"]["params"]["sort_type"] == "score"
```

- [ ] **Step 2: Verify tests fail because the module is missing**

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_reddit_harvest.py -q
```

- [ ] **Step 3: Implement PullPush submission search**

Use `https://api.pullpush.io/reddit/search/submission/` with:

```python
params = {
    "q": query,
    "subreddit": subreddit,
    "is_video": "true",
    "over_18": "false",
    "after": "30d",
    "sort": "desc",
    "sort_type": "score",
    "size": min(size, 100),
}
```

Convert each result into candidate metadata containing `source_id`, `title`, `permalink`, `url`, `media_url`, `subreddit`, `score`, `num_comments`, `created_utc`, and `query`.

- [ ] **Step 4: Implement Reddit relevance scoring**

Score entity/title overlap, approved gaming subreddit match, Reddit score/comments, freshness, and video URL availability. Penalize GTA 5/mod content when the draft is explicitly about GTA 6.

- [ ] **Step 5: Verify PullPush tests pass**

Run the command from Step 2.

- [ ] **Step 6: Commit Reddit discovery**

```powershell
git add verticals/reddit_harvest.py tests/test_reddit_harvest.py
git commit -m "feat: discover relevant Reddit videos"
```

### Task 3: Download and Mark Reddit Candidates

**Files:**
- Modify: `verticals/reddit_harvest.py`
- Modify: `tests/test_reddit_harvest.py`

- [ ] **Step 1: Write a failing download/manifest test**

The test must mock `subprocess.run`, create a downloaded MP4, and assert:

```python
assert result["assets"][0]["source"] == "reddit_harvest"
assert result["assets"][0]["protected"] is True
assert result["assets"][0]["status"] == "candidate"
assert result["assets"][0]["subreddit"] == "gaming"
assert Path(result["manifest_path"]).exists()
```

- [ ] **Step 2: Run the focused test and verify failure**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_reddit_harvest.py::test_harvest_reddit_videos_downloads_candidates -q
```

- [ ] **Step 3: Implement yt-dlp download and manifest persistence**

Use the Reddit permalink first because yt-dlp can resolve `v.redd.it` audio/video variants. Store clips under `harvested_reddit/<submission_id>/`. Save `reddit_harvest_manifest.json` with `queries`, `assets`, `rejected`, and rejection reasons.

- [ ] **Step 4: Add bounded parallel downloads**

Use `ThreadPoolExecutor(max_workers=min(6, len(candidates)))`. Each worker owns a unique output directory, so workers do not share files.

- [ ] **Step 5: Verify download tests pass**

Run all `tests/test_reddit_harvest.py` tests.

- [ ] **Step 6: Commit Reddit downloads**

```powershell
git add verticals/reddit_harvest.py tests/test_reddit_harvest.py
git commit -m "feat: harvest Reddit video candidates"
```

### Task 4: Enrich Clips and Remove Duplicate Media

**Files:**
- Modify: `verticals/video_candidates.py`
- Modify: `verticals/yt_harvest.py`
- Modify: `verticals/reddit_harvest.py`
- Modify: `tests/test_video_candidates.py`

- [ ] **Step 1: Write failing media-hash and contact-sheet tests**

Test that downloaded clips receive `width`, `height`, `is_vertical`, `actual_duration`, `media_hash`, and `contact_sheet_path`. Test that identical files from Reddit and YouTube collapse to the higher-scored candidate.

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests\test_video_candidates.py -q
```

- [ ] **Step 3: Implement ffprobe metadata and file hashing**

Use ffprobe JSON output for video dimensions/duration and SHA-256 over file bytes for deduplication. Set `is_vertical = height >= width`.

- [ ] **Step 4: Implement a three-frame contact sheet**

Extract frames at 20%, 50%, and 80% with ffmpeg and combine them using Pillow. Save beside each downloaded clip. Do not call OpenAI during this task; the contact sheet is editor metadata and optional later vision input.

- [ ] **Step 5: Verify enrichment/deduplication tests pass**

Run the command from Step 2.

- [ ] **Step 6: Commit enrichment**

```powershell
git add verticals/video_candidates.py verticals/yt_harvest.py verticals/reddit_harvest.py tests/test_video_candidates.py
git commit -m "feat: enrich and deduplicate video candidates"
```

### Task 5: Video-First Parallel Production Orchestration

**Files:**
- Modify: `verticals/__main__.py`
- Modify: `verticals/visual_plan.py`
- Modify: `niches/gaming.yaml`
- Modify: `tests/test_main.py`
- Modify: `tests/test_visual_plan.py`

- [ ] **Step 1: Write failing source-orchestration tests**

Test that YouTube and Reddit harvesting are submitted concurrently, their candidates are combined/deduplicated, and OpenAI b-roll prompts are not resolved when the video candidate threshold is met.

```python
assert sources == {"youtube_harvest", "reddit_harvest"}
assert generate_broll.call_count == 0
```

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_main.py tests/test_visual_plan.py -q
```

- [ ] **Step 3: Add gaming source policy**

Update `niches/gaming.yaml`:

```yaml
editing:
  prefer_scraped_video: true
  youtube_clips: [4, 8]
  reddit_clips: [4, 8]
  meme_beats: [6, 10]
  ai_images: [0, 1]
  minimum_video_candidates: 8
  harvest_workers: 4
```

- [ ] **Step 4: Run independent harvesters concurrently**

In `cmd_produce`, submit YouTube harvest, Reddit harvest, and non-harvest visual resolution through a bounded executor. Combine results only after all futures finish. Preserve deterministic order by sorting videos by relevance score, then source, then source id.

- [ ] **Step 5: Make OpenAI images conditional**

When `prefer_scraped_video` is true and unique harvested video count is at least `minimum_video_candidates`, omit nonessential AI-image items. Keep one AI-image item only if it is explicitly protected and no video candidate matches its transcript beat.

- [ ] **Step 6: Verify orchestration tests pass**

Run the command from Step 2.

- [ ] **Step 7: Commit orchestration**

```powershell
git add verticals/__main__.py verticals/visual_plan.py niches/gaming.yaml tests/test_main.py tests/test_visual_plan.py
git commit -m "feat: prefer parallel harvested video assets"
```

### Task 6: Transcript-Aware Editor Source Balancing

**Files:**
- Modify: `verticals/editor_plan.py`
- Modify: `tests/test_editor_plan.py`

- [ ] **Step 1: Write failing editor prompt/validation tests**

Assert that the prompt contains full timed transcript segments, candidate title/source/subreddit/relevance/contact-sheet metadata, and explicit source targets. Assert validation preserves every selected harvested video and rejects repeated meme files unless `reuse_reason` is present.

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_editor_plan.py -q
```

- [ ] **Step 3: Add editor source targets**

Send:

```json
{
  "source_targets": {
    "youtube_harvest": {"minimum": 4, "maximum": 8},
    "reddit_harvest": {"minimum": 4, "maximum": 8},
    "imgflip": {"minimum": 6, "maximum": 10},
    "openai": {"minimum": 0, "maximum": 1}
  }
}
```

Tell the editor to align clip title/query/labels to transcript segment text and to return `source_start_seconds` for harvested videos.

- [ ] **Step 4: Validate source ranges and full coverage**

Reject unknown assets, duplicate files without reuse reasons, source ranges outside the downloaded clip duration, and timelines that do not cover the voiceover. Preserve the existing full-duration retiming fallback.

- [ ] **Step 5: Verify editor tests pass**

Run the command from Step 2.

- [ ] **Step 6: Commit editor balancing**

```powershell
git add verticals/editor_plan.py tests/test_editor_plan.py
git commit -m "feat: balance transcript-aware harvested clips"
```

### Task 7: Render Selected Source Segments

**Files:**
- Modify: `verticals/assemble.py`
- Modify: `tests/test_assemble.py`

- [ ] **Step 1: Write failing source-range tests**

Test that a harvested video timeline item with `source_start_seconds=8.5` and `duration_seconds=2.5` passes `-ss 8.5` and `-t 2.5` to ffmpeg. Test that images and memes remain unchanged.

- [ ] **Step 2: Verify tests fail**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_assemble.py -q
```

- [ ] **Step 3: Add source offset to `_fit_clip`**

Change the signature to:

```python
def _fit_clip(src: Path, out_path: Path, duration: float, source_start: float = 0.0):
```

Place `-ss <source_start>` before `-i`, retain `-stream_loop -1`, and keep the normalized 1080x1920 output settings.

- [ ] **Step 4: Verify assembly tests pass**

Run the command from Step 2.

- [ ] **Step 5: Commit segment rendering**

```powershell
git add verticals/assemble.py tests/test_assemble.py
git commit -m "feat: render selected harvested clip ranges"
```

### Task 8: Backend Visibility and Documentation

**Files:**
- Modify: `verticals/server.py`
- Modify: `.env.example`
- Modify: `README.md`
- Modify: `tests/test_server.py`

- [ ] **Step 1: Write failing API summary test**

Assert completed job summaries include:

```python
assert result["visual_summary"]["youtube_harvest"] >= 0
assert result["visual_summary"]["reddit_harvest"] >= 0
assert result["harvest_summary"]["rejected"] >= 0
```

- [ ] **Step 2: Verify the server test fails**

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_server.py -q
```

- [ ] **Step 3: Expose harvest diagnostics**

Include source counts, downloaded/rejected counts, and YouTube/Reddit manifest paths in `_draft_summary`. Update the frontend badges from “Pexels” to “Harvested video” where appropriate.

- [ ] **Step 4: Document configuration**

Add these optional environment values:

```text
VIDEO_HARVEST_ENABLED=true
YOUTUBE_HARVEST_DOWNLOADS=8
REDDIT_HARVEST_DOWNLOADS=8
REDDIT_HARVEST_AFTER=30d
MINIMUM_VIDEO_CANDIDATES=8
```

Document PullPush endpoint usage, yt-dlp requirement, storage paths, manifest fields, and how to disable external harvesting.

- [ ] **Step 5: Run full verification**

```powershell
$env:TMP='D:\youtube-shorts-pipeline\.tmp'
$env:TEMP='D:\youtube-shorts-pipeline\.tmp'
$env:USERPROFILE='D:\youtube-shorts-pipeline\.tmp\home'
.\.venv\Scripts\python.exe -m compileall verticals -q
.\.venv\Scripts\python.exe -m pytest -q -o cache_dir=.tmp/.pytest_cache
```

Expected: compile exits `0`; all tests pass.

- [ ] **Step 6: Commit documentation and backend visibility**

```powershell
git add verticals/server.py .env.example README.md tests/test_server.py
git commit -m "docs: expose video harvest diagnostics"
```

## Acceptance Criteria

- PullPush searches relevant, recent, SFW video submissions from niche subreddits.
- YouTube and Reddit discovery/download run independently and concurrently.
- Duplicate media from multiple platforms is stored only once.
- Gaming jobs target at least eight unique harvested video candidates before generating OpenAI images.
- OpenAI image use is zero or one for normal gaming jobs with adequate harvested footage.
- The editor receives timed transcript segments and rich candidate metadata.
- The editor uses more harvested videos and varied memes than stock footage/AI images.
- Harvested source ranges are rendered correctly and the final video matches voiceover duration.
- Job UI and manifests show downloaded, selected, rejected, and avoided assets.
- The complete test suite passes.
