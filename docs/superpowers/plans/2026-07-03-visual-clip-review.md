# Visual Clip Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Review sampled frames from harvested clips, retain only relevant source ranges, and add Vimeo as a parallel source.

**Architecture:** Provider harvesters emit one normalized candidate schema. A frame sampler creates six-frame contact sheets, a vision reviewer validates OpenAI JSON into keep/discard decisions, and the existing editor receives only approved assets with enforceable source ranges.

**Tech Stack:** Python 3.10+, requests, Pillow, ffmpeg, yt-dlp, OpenAI Chat Completions, pytest

---

### Task 1: Six-frame clip sampling

**Files:**
- Create: `verticals/clip_frames.py`
- Create: `tests/test_clip_frames.py`

- [ ] Write tests for deterministic sample timestamps and extracted frame metadata.
- [ ] Run `python -m pytest tests/test_clip_frames.py -q` and confirm imports fail.
- [ ] Implement six evenly distributed samples, ffmpeg extraction, and labelled contact-sheet creation.
- [ ] Run `python -m pytest tests/test_clip_frames.py -q` and confirm all tests pass.

### Task 2: Vision review and fallback

**Files:**
- Create: `verticals/clip_review.py`
- Create: `tests/test_clip_review.py`

- [ ] Write tests for JSON decision validation, wrong-topic rejection, useful-range clamping, metadata fallback, batching, and manifest persistence without deleting files.
- [ ] Run `python -m pytest tests/test_clip_review.py -q` and confirm imports fail.
- [ ] Implement base64 contact-sheet requests to OpenAI, per-batch failure fallback, validated decisions, and manifest/log summaries.
- [ ] Run `python -m pytest tests/test_clip_review.py -q` and confirm all tests pass.

### Task 3: Vimeo harvester

**Files:**
- Create: `verticals/vimeo_harvest.py`
- Create: `tests/test_vimeo_harvest.py`
- Modify: `verticals/config.py`
- Modify: `.env.example`

- [ ] Write tests for API discovery, HTML URL extraction, metadata scoring, download normalization, and failure isolation.
- [ ] Run `python -m pytest tests/test_vimeo_harvest.py -q` and confirm imports fail.
- [ ] Implement token-backed Vimeo API discovery, HTML fallback, yt-dlp download, and `VIMEO_ACCESS_TOKEN` resolution.
- [ ] Run `python -m pytest tests/test_vimeo_harvest.py -q` and confirm all tests pass.

### Task 4: Parallel orchestration and editor range enforcement

**Files:**
- Modify: `verticals/video_harvest.py`
- Modify: `verticals/editor_plan.py`
- Modify: `verticals/niche.py`
- Modify: `verticals/__main__.py`
- Modify: `tests/test_video_harvest.py`
- Modify: `tests/test_editor_plan.py`
- Modify: `tests/test_niche.py`

- [ ] Write tests proving three harvesters run concurrently, discarded clips stay out of the editor pool, review metadata reaches the prompt, and source offsets clamp to approved ranges.
- [ ] Run the targeted tests and confirm the new assertions fail.
- [ ] Integrate Vimeo, run clip review before timeline creation, add defaults and environment overrides, and enforce approved ranges in timeline validation.
- [ ] Run the targeted tests and confirm all pass.

### Task 5: Documentation and complete verification

**Files:**
- Modify: `README.md`

- [ ] Document `VIMEO_ACCESS_TOKEN`, vision review behavior, manifests, and fallback behavior.
- [ ] Run `python -m pytest -q` with workspace-local `HOME` and `USERPROFILE`.
- [ ] Run `python -m compileall -q verticals tests`.
- [ ] Run `git diff --check` and inspect `git diff --stat`.
