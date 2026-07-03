# Semantic Asset Editing System Specification

**Status:** Proposed  
**Date:** 2026-07-03  
**Project:** Verticals / YouTube Shorts Pipeline  
**Scope:** Search refinement, harvested-video inspection, semantic asset matching, source clipping, quality filtering, and editor validation

## 1. Purpose

The pipeline currently gathers useful assets and asks an editor LLM to arrange them, but the editor receives an effectively unordered pool. Metadata relevance alone cannot prove that a downloaded clip visually depicts the spoken sentence. It also cannot identify the useful portion of a longer video, detect visual defects reliably, or enforce all final-edit requirements.

This system introduces a deterministic semantic layer between asset acquisition and editing. Every spoken beat receives its own search intent. Every downloaded video receives technical and visual inspection. Qualified assets are ranked against transcript beats. The editor receives those ranked matches and exact usable source ranges. A final validator either repairs or rejects timelines that violate editing policy.

## 2. Goals

1. Reject downloaded clips that are visually unrelated to the script.
2. Match each timed transcript beat to relevant assets before the editor LLM runs.
3. Identify useful source ranges inside longer videos.
4. Reject technically or editorially unsuitable assets.
5. Generate search tags per script beat rather than only five global tags.
6. Enforce timeline duration, pacing, freshness, uniqueness, meme alignment, and source diversity.
7. Preserve graceful fallback behavior when vision APIs or individual media providers fail.
8. Save enough evidence to explain why every asset was accepted, rejected, or selected.

## 3. Non-Goals

1. Full non-linear editing comparable to Premiere Pro or Resolve.
2. Face recognition or identification of private individuals.
3. Automatic copyright clearance.
4. Generating synthetic gameplay video.
5. Frame-perfect beat synchronization to music in the first release.
6. Replacing Whisper word timestamps.

## 4. Success Metrics

The implementation is successful when all of the following hold:

- At least 80% of non-meme cuts have a semantic match score of `0.65` or higher.
- No rejected asset enters the final editor manifest.
- The first cut is fresh for the current reuse window unless the timeline declares an approved callback.
- Final timeline coverage differs from voiceover duration by no more than `0.10` seconds.
- Median visual cut duration is between `2.0` and `4.0` seconds for meme-heavy gaming edits.
- No asset repeats without a non-empty `reuse_reason` accepted by validation.
- Every meme overlaps a transcript beat classified as reaction, joke, surprise, escalation, or opinion.
- Final edits meet configured minimum source diversity whenever enough qualified assets exist.
- Every rejected video has at least one machine-readable rejection reason.

## 5. Pipeline Architecture

```text
Topic + Research
      |
      v
Draft + Script Beat Search Plan
      |
      +-------------------------------+
      |                               |
      v                               v
Video/Image/Meme Harvesting       Voiceover + Whisper
      |                               |
      v                               v
Technical Inspection             Timed Transcript Beats
      |
      v
Contact Sheets + Sample Frames
      |
      v
Vision Relevance and Quality Review
      |
      v
Qualified Asset Pool
      |
      v
Beat-to-Asset Matcher <---------- Timed Transcript Beats
      |
      v
Editor LLM with ranked candidates and usable ranges
      |
      v
Deterministic Timeline Validator and Repair
      |
      v
Assembly + Validation Report
```

The stages remain resumable through the existing pipeline state. New expensive stages persist artifacts and are skipped when their input fingerprint has not changed.

## 6. Canonical Data Contracts

### 6.1 Script Beat

The draft LLM produces semantic beats before timestamps exist. Whisper timestamps are attached later.

```json
{
  "beat_id": "beat_001",
  "script_text": "The leaked map appears almost twice as large.",
  "intent": "evidence",
  "entities": ["GTA 6", "Vice City", "leaked map"],
  "visual_description": "side-by-side GTA 6 leaked map size comparison",
  "search_queries": [
    "GTA 6 leaked map size comparison",
    "Vice City GTA 6 map overlay",
    "GTA 6 map leak analysis footage"
  ],
  "preferred_asset_types": ["youtube_harvest", "web_research"],
  "avoid": ["generic gamer desk", "unrelated GTA 5 gameplay"],
  "start": 12.4,
  "end": 16.8
}
```

Rules:

- Drafts contain between 6 and 12 beats.
- Each beat contains exactly three unique search queries.
- Queries must name concrete entities or visuals from that beat.
- `start` and `end` are absent until transcript alignment completes.
- Allowed intents are `hook`, `context`, `evidence`, `reaction`, `escalation`, `joke`, `opinion`, and `cta`.

### 6.2 Inspected Asset

```json
{
  "asset_id": "asset_014",
  "source": "youtube_harvest",
  "source_id": "abc123",
  "path": "C:/.../abc123.mp4",
  "url": "https://youtube.com/watch?v=abc123",
  "media_hash": "sha256...",
  "perceptual_hashes": ["phash1", "phash2", "phash3"],
  "width": 1080,
  "height": 1920,
  "actual_duration": 41.2,
  "fps": 30.0,
  "is_vertical": true,
  "contact_sheet_path": "C:/.../contact_sheet.jpg",
  "sample_frames": [
    {"time": 2.0, "path": "C:/.../frame_000.jpg"},
    {"time": 8.0, "path": "C:/.../frame_001.jpg"}
  ],
  "quality": {
    "technical_score": 0.91,
    "watermark_probability": 0.08,
    "embedded_caption_probability": 0.15,
    "talking_head_probability": 0.22,
    "crop_safety_score": 0.86,
    "sharpness_score": 0.77
  },
  "vision": {
    "summary": "GTA-style city map shown beside a comparison graphic",
    "visible_entities": ["map", "city grid", "size labels"],
    "unsafe": false
  },
  "usable_ranges": [
    {"start": 6.5, "end": 11.2, "description": "clear map comparison", "score": 0.92}
  ],
  "status": "qualified",
  "rejection_reasons": []
}
```

### 6.3 Beat Match

```json
{
  "beat_id": "beat_003",
  "asset_id": "asset_014",
  "semantic_score": 0.88,
  "entity_score": 1.0,
  "visual_score": 0.84,
  "quality_score": 0.91,
  "freshness_score": 1.0,
  "combined_score": 0.90,
  "source_start_seconds": 6.5,
  "source_end_seconds": 10.0,
  "reason": "The frame directly shows the map-size comparison named in the sentence."
}
```

### 6.4 Validation Report

```json
{
  "valid": true,
  "repaired": false,
  "metrics": {
    "coverage_seconds": 58.42,
    "target_seconds": 58.42,
    "median_cut_seconds": 2.85,
    "unique_asset_ratio": 1.0,
    "source_count": 4,
    "matched_cut_ratio": 0.89
  },
  "errors": [],
  "warnings": [
    {"code": "LOW_REDDIT_COUNT", "message": "Only one qualified Reddit clip was available."}
  ],
  "repairs": []
}
```

## 7. Script Beats and Search Refinement

### 7.1 Generation

The existing draft LLM call gains a `script_beats` field. This avoids a second drafting API call. The global five `search_tags` remain for broad discovery, while beat queries provide precision.

Each beat must:

- Cover a contiguous sentence or short group of sentences.
- Preserve the script’s original order.
- Include three search queries suitable across YouTube, Reddit, DuckDuckGo, Pexels, and Pixabay.
- Prefer concrete visual nouns over emotions.
- Include specific entities from verified research.
- Avoid generic queries such as `gaming setup`, `angry gamer`, or `technology background`.

### 7.2 Validation and Fallback

`normalize_script_beats(draft)` validates LLM output. Missing beats are generated deterministically from script sentences. Fallback queries combine named entities and meaningful nouns from each sentence; they never substitute niche-specific stock phrases.

The five global tags are derived from the highest-priority beat queries when the LLM omits global tags. This keeps broad and local discovery consistent.

### 7.3 Provider Use

- YouTube and Reddit search every beat query, with per-query result limits.
- Web-image discovery searches evidence and context beats first.
- Pexels and Pixabay receive only queries whose preferred type includes stock footage.
- Meme generation consumes reaction, joke, escalation, and opinion beats.
- Provider adapters may append syntax such as `shorts`; they may not replace the semantic query.

## 8. Transcript Alignment

Whisper words are grouped into sentence-like transcript segments using punctuation and pauses of at least `0.45` seconds. Script beats are aligned to transcript segments in order using normalized token overlap.

Alignment rules:

1. Preserve beat ordering.
2. A transcript segment can contribute to only one primary beat.
3. Adjacent segments may merge when the script beat spans multiple sentences.
4. A beat with alignment confidence below `0.45` receives proportional timestamps based on neighboring aligned beats.
5. The first beat starts at `0.0`; the last beat ends at voiceover duration.
6. Gaps and overlaps are repaired deterministically.

The resulting timed beats, not arbitrary 12-word groups, become the editor’s transcript context.

## 9. Better Source Clipping

### 9.1 Download Policy

Harvesters may accept source videos up to `10` minutes when metadata relevance is high. Download format remains capped at 1920 pixels. Search results are still filtered before download to control bandwidth.

### 9.2 Frame Sampling

Videos are sampled at scene-aware and fixed intervals:

- Scene changes detected with FFmpeg `select='gt(scene,0.30)'`.
- At most 12 scene frames per asset.
- If fewer than four scene frames exist, add evenly spaced frames.
- Never sample the first or final `0.5` seconds unless the video is shorter than three seconds.

### 9.3 Usable Ranges

Vision review groups adjacent useful frames into candidate ranges. Every range includes start, end, description, and score. Ranges shorter than `1.0` second are discarded. Ranges longer than `8.0` seconds are split around scene boundaries.

The editor chooses `source_start_seconds` from these ranges. Validation clamps the requested source interval to a declared usable range rather than merely clamping it to total duration.

## 10. Technical Quality Filters

Technical inspection runs locally before paid vision review.

### 10.1 Hard Rejections

Reject when any condition is true:

- Width or height is zero.
- Duration is below `1.0` second.
- Resolution is below `480x480`.
- File cannot be decoded by FFmpeg.
- More than 40% of sampled frames are nearly black or frozen.
- Exact SHA-256 duplicates another candidate.
- Perceptual duplicate distance is below configured threshold and the competing asset has a higher score.

### 10.2 Soft Penalties

- Landscape source requiring severe portrait crop: `-0.20`.
- Resolution below 720p: `-0.15`.
- Persistent embedded subtitles: `-0.15`.
- Watermark or platform logo: `-0.25`.
- Generic talking head with no story-specific visual: `-0.20`.
- Low sharpness: up to `-0.15`.

Soft penalties lower quality score but do not reject unless total quality falls below `0.45`.

### 10.3 Portrait Crop Safety

Crop safety is evaluated from subject bounding regions returned by vision review. A landscape clip is acceptable when its primary subject remains inside the central 56.25% portrait crop for the selected range. Otherwise the clip must use `contain_pad` or be rejected for sources where padded video is disallowed.

## 11. Vision Relevance Review

### 11.1 Inputs

The vision model receives:

- Contact sheet and up to 12 timestamped sample frames.
- Source title, uploader, search query, and URL domain.
- Script title and verified entities.
- All script beats, each with visual description and avoidance terms.

### 11.2 Output

Vision responses use strict JSON and return:

- Visual summary.
- Visible entities and on-screen text summary.
- Watermark, embedded-caption, talking-head, and crop-safety probabilities.
- Relevance score for each beat.
- Useful timestamps for matching beats.
- Rejection recommendation and reasons.

### 11.3 Cost Control

- Local hard filters run first.
- Contact sheets are resized to a maximum long edge of 1280 pixels.
- One vision request reviews one asset against all beats.
- Review results are cached by `media_hash + beat_plan_hash + model`.
- At most the highest-ranked 20 video candidates receive vision review by default.
- If no vision key is available, metadata matching continues with `vision_unavailable=true`; the pipeline does not fail.

### 11.4 Relevance Thresholds

- `>= 0.75`: strong match.
- `0.55–0.74`: usable supporting match.
- `0.40–0.54`: fallback only.
- `< 0.40`: unrelated and rejected unless the asset is a deliberate generic transition.

## 12. Beat-to-Asset Matching

Matching is deterministic after vision review. The editor LLM does not calculate the initial ranking.

Combined score:

```text
0.40 * semantic_score
+ 0.20 * entity_score
+ 0.15 * visual_score
+ 0.15 * quality_score
+ 0.10 * freshness_score
- reuse_penalty
```

Where:

- `semantic_score` compares beat query/description with asset metadata and vision summary.
- `entity_score` measures verified entity overlap.
- `visual_score` is the vision model’s beat relevance.
- `quality_score` comes from technical and visual quality checks.
- `freshness_score` comes from cross-job asset history.
- `reuse_penalty` discourages assigning one asset to multiple beats.

Each beat receives up to five ranked candidates. At least two should come from different sources when qualified options exist. Memes are ranked only for compatible intents.

## 13. Editor Input and Behavior

The editor receives:

- Timed script beats.
- Up to five ranked candidates per beat.
- Candidate reasons and scores.
- Declared usable source ranges.
- Music plan and transcript words.
- Source minimums and maximums.
- Previous-job freshness metadata.

The editor may select only candidates attached to the active beat, except for transitions explicitly tagged `cross_beat_allowed`. It may not use rejected assets. It must choose source timestamps inside a declared usable range.

The opening beat must prefer a strong, fresh video match. A meme may open only when the script’s first beat is reaction, joke, or surprise and no strong fresh video exists.

## 14. Deterministic Timeline Validation

Validation runs after the editor response and before assembly.

### 14.1 Errors

The following invalidate a timeline:

- Unknown or rejected asset.
- Missing timeline coverage greater than `0.10` seconds.
- Overlap greater than `0.05` seconds.
- Repeated asset without accepted `reuse_reason`.
- Source timestamp outside a declared usable range.
- Opening asset used in any recent job inside the configured reuse window.
- Meme assigned to a semantically incompatible beat.
- Cut shorter than `0.75` seconds or longer than `6.0` seconds without an explicit exception.

### 14.2 Warnings

- Median cut duration outside configured target.
- Source minimum unmet because insufficient qualified assets exist.
- Match score below `0.55`.
- More than 40% of timeline from one provider.
- Consecutive cuts from the same source or uploader.

### 14.3 Repairable Violations

The validator may repair:

- Small timeline gaps by extending the preceding cut.
- Small overlaps by moving the later cut start.
- Out-of-range source offsets by clamping to the best usable range.
- Long cuts by splitting across the next ranked unused candidate.
- Missing source diversity by substituting a qualified candidate for the same beat.

It must not repair unrelated assets, rejected assets, unexplained repeats, or incompatible memes. Those trigger one editor retry with structured validation feedback. If the retry fails, the deterministic fallback builder creates a timeline from ranked beat matches.

## 15. Meme Alignment

Meme eligibility is based on beat intent and transcript language.

Eligible intents:

- `reaction`
- `joke`
- `escalation`
- `opinion`
- `hook` when surprise is explicit

Each meme asset stores `target_beat_id`, generated caption rationale, and semantic keywords. Validation rejects memes assigned outside their target beat unless their keywords overlap the new beat and the editor provides a reason.

No meme template or rendered meme may repeat within one timeline. Cross-job meme-template history applies a soft penalty rather than a hard rejection because the caption can make a template meaningfully different.

## 16. Source Diversity Policy

Configuration continues to define source ranges. Enforcement uses qualified availability:

```yaml
editor_validation:
  cut_duration_seconds: [2.0, 4.0]
  hard_cut_bounds_seconds: [0.75, 6.0]
  minimum_semantic_score: 0.55
  strong_semantic_score: 0.75
  maximum_single_source_ratio: 0.40
  fresh_opening_required: true
  asset_reuse_window_jobs: 10
  editor_retry_count: 1
```

If a configured minimum exceeds qualified inventory, validation emits a warning and uses all available qualified assets. It never inserts a rejected asset solely to satisfy diversity.

## 17. Persistence and Resumability

New pipeline stages:

1. `beat_plan`
2. `asset_inspection`
3. `vision_review`
4. `beat_matching`
5. `editor_validation`

Each stage stores artifacts in the draft state. Expensive artifacts also live beside downloaded media:

```text
work_<job>_<lang>/
  inspection/
    <asset-key>/
      probe.json
      contact_sheet.jpg
      frames/
      vision_review.json
  beat_matches.json
  editor_validation.json
```

Cache fingerprints include all inputs that affect output. Changing only captions does not rerun harvesting. Changing the script beat plan invalidates vision relevance and matching but may reuse technical probes and frames.

## 18. Error Handling

- FFmpeg probe failure rejects only that asset.
- Vision API failure marks the asset `vision_unavailable` and allows metadata-only scoring.
- Malformed vision JSON retries once, then falls back.
- No qualified video assets triggers images and memes rather than pipeline failure.
- No qualified asset for one beat permits the best fallback asset scoring at least `0.40`.
- No asset scoring `0.40` uses a topic-specific generated image.
- Editor validation failure retries the editor once with exact error codes.
- Failed deterministic fallback stops assembly with a clear `No valid timeline` error.

## 19. Security and Content Safety

- Vision prompts treat source titles and on-screen text as untrusted data.
- Downloaded metadata cannot alter system instructions.
- API keys remain resolved through existing config helpers.
- Vision request logs exclude base64 image payloads and secrets.
- NSFW or unsafe vision classifications reject assets before editor matching.
- URLs and provenance remain attached to assets for later rights review.

## 20. Observability

Console and job state expose:

- Candidates discovered per provider.
- Technical rejections by reason.
- Assets sent to vision review and cache-hit count.
- Qualified assets and relevance distribution.
- Number of beats with strong, supporting, fallback, or no matches.
- Editor validation errors, warnings, repairs, and retry count.
- Final source mix, unique-asset ratio, median cut duration, and semantic match ratio.

The frontend should eventually render the validation report, but UI work is outside this specification.

## 21. Proposed Module Boundaries

- `verticals/script_beats.py`: Beat validation, fallback generation, and transcript alignment.
- `verticals/video_inspection.py`: Technical probe, scene sampling, sharpness/freeze checks, and crop metadata.
- `verticals/vision_review.py`: Multimodal API request, response validation, and cache.
- `verticals/asset_quality.py`: Hard rejection and quality-score policy.
- `verticals/asset_matcher.py`: Beat-to-asset scoring and ranked candidate production.
- `verticals/timeline_validation.py`: Timeline metrics, violations, repairs, and validation report.
- `verticals/video_candidates.py`: Keep normalization, exact hashing, and cross-source deduplication; delegate inspection details.
- `verticals/editor_plan.py`: Build editor prompt from ranked beat matches and parse editor response.
- `verticals/__main__.py`: Orchestrate resumable stages only; no scoring logic.

## 22. Test Strategy

### 22.1 Unit Tests

- Beat normalization returns ordered, unique beat IDs and three specific queries.
- Transcript alignment covers the complete voiceover without overlap.
- Technical filters reject corrupt, tiny, frozen, and exact duplicate videos.
- Perceptual hash rejects visually duplicate videos with different encodings.
- Vision response parser rejects malformed or incomplete JSON.
- Quality scoring applies each penalty exactly once.
- Matcher ranks a direct visual match above generic high-quality footage.
- Matcher penalizes recently used assets.
- Source offsets remain inside usable ranges.
- Meme compatibility follows beat intent.
- Timeline validation catches every hard error and computes metrics correctly.
- Repair logic closes small gaps without introducing overlaps.

### 22.2 Integration Tests

- A fixture script, Whisper word list, and mixed asset pool produce complete ranked beat matches.
- Vision failure still produces a metadata-only timeline.
- An editor response containing a repeated asset is rejected and retried.
- An editor response with an invalid source offset is repaired.
- Insufficient Reddit assets produces a warning, not an unrelated insertion.
- Assembly consumes validated `source_start_seconds` and exact durations.

### 22.3 Golden Fixtures

Maintain small checked-in fixture metadata and generated color-pattern videos. Do not check copyrighted harvested media into Git. Vision client tests use recorded JSON responses and local fixture images.

### 22.4 End-to-End Acceptance

Run three topics from different niches. For each output, save:

- Beat plan.
- Inspection manifest.
- Vision decisions.
- Beat matches.
- Editor timeline.
- Validation report.
- Final MP4 duration probe.

All success metrics in Section 4 must pass before enabling strict validation by default.

## 23. Rollout Strategy

### Phase 1: Observe

Generate beats, inspections, vision scores, matches, and reports without changing editor selection. Compare proposed matches with existing timelines.

### Phase 2: Match-Assisted Editing

Feed ranked candidates to the editor, but treat low relevance and diversity as warnings. Enforce only corrupt/rejected assets, unexplained repeats, and duration coverage.

### Phase 3: Strict Validation

Enable all thresholds and one editor retry. Use deterministic beat-match fallback when retry fails.

### Phase 4: Tune

Adjust thresholds using validation reports and manual review across at least 20 generated videos. Thresholds remain configuration, not source-code constants.

## 24. Acceptance Criteria

This specification is complete when implementation can demonstrate:

1. A draft with per-beat search queries.
2. Timed beats derived from Whisper words.
3. Local technical inspection before paid vision calls.
4. Vision summaries, relevance scores, and usable source ranges persisted per asset.
5. Rejected assets absent from editor input.
6. Five ranked candidate assets per beat when inventory permits.
7. Editor cuts constrained to matched beats and usable source ranges.
8. Strict detection of unexplained reuse, stale opening clips, incomplete duration, invalid cut pacing, incompatible memes, and insufficient source diversity.
9. A machine-readable validation report stored in pipeline state.
10. Successful fallback generation when vision review is unavailable.

