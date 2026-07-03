# Meme-Heavy Editing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce fast-cut gaming videos from 2-4 portrait Pexels clips, 4-6 free Imgflip memes, and 1-2 portrait OpenAI images under niche control.

**Architecture:** `verticals/niche.py` normalizes editing defaults, `verticals/visual_plan.py` validates and resolves a provider-neutral timeline, and small provider clients fetch Imgflip/Pexels/OpenAI assets. `verticals/assemble.py` consumes ordered timeline items and normalizes their durations to the voiceover.

**Tech Stack:** Python, PyYAML, requests, Pillow, ffmpeg, pytest, OpenAI Images API, Imgflip REST API, Pexels MCP.

---

### Task 1: Niche Editing Configuration

**Files:**
- Modify: `niches/gaming.yaml`
- Modify: `niches/general.yaml`
- Modify: `verticals/niche.py`
- Modify: `tests/test_niche.py`

- [ ] Write a failing test asserting `get_editing_config(load_niche("gaming"))` returns `meme_heavy`, count ranges `[2, 4]`, `[4, 6]`, `[1, 2]`, cut range `[2, 5]`, and allowed effects.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_niche.py -q`; expect import or assertion failure.
- [ ] Add YAML blocks and `get_editing_config`, normalizing two-number ranges, style, and effect allow-list while using balanced defaults.
- [ ] Re-run the niche tests; expect pass.

### Task 2: Draft Visual Plan

**Files:**
- Create: `verticals/visual_plan.py`
- Modify: `verticals/draft.py`
- Create: `tests/test_visual_plan.py`
- Modify: `tests/test_draft.py`

- [ ] Write failing tests for `normalize_visual_plan`: retain valid items, clamp duration to 2-5 seconds, reject unknown types/effects, enforce niche maximums, and convert legacy prompts to AI-image items.
- [ ] Write a failing draft prompt test asserting exact source ranges and `visual_plan` JSON schema appear for gaming.
- [ ] Run the two test files; expect missing module/schema failures.
- [ ] Implement `normalize_visual_plan(draft, editing)` and add the structured plan to the LLM output contract and saved draft.
- [ ] Re-run both test files; expect pass.

### Task 3: Portrait OpenAI Images

**Files:**
- Modify: `verticals/broll.py`
- Modify: `tests/test_broll.py`

- [ ] Write a failing test mocking `generate_openai_image` and asserting `generate_broll` passes `size="1024x1536"` plus portrait-safe-area prompt language.
- [ ] Run `.venv\Scripts\python.exe -m pytest tests/test_broll.py -q`; expect square-size assertion failure.
- [ ] Change b-roll generation to portrait size and safe-area prompt, preserving final `1080x1920` crop.
- [ ] Re-run the b-roll tests; expect pass.

### Task 4: Free Imgflip Client

**Files:**
- Create: `verticals/imgflip.py`
- Modify: `verticals/config.py`
- Create: `tests/test_imgflip.py`

- [ ] Write failing tests for template-name scoring, `get_memes`, form-encoded `caption_image`, missing credentials, redacted errors, and immediate image download.
- [ ] Run the Imgflip tests; expect missing module failure.
- [ ] Implement `get_imgflip_credentials`, `fetch_templates`, `select_template`, and `create_meme`; POST credentials only in the HTTPS body and never include them in exceptions/logging.
- [ ] Re-run the Imgflip tests; expect pass.

### Task 5: Resolve Mixed Visual Assets

**Files:**
- Extend: `verticals/visual_plan.py`
- Modify: `verticals/__main__.py`
- Create: `tests/test_visual_assets.py`

- [ ] Write failing tests that resolve configured item types in order, produce 2-4 Pexels and 4-6 Imgflip assets for gaming plans, avoid duplicate Pexels paths, and fall back to portrait AI then solid frames per failed item.
- [ ] Run the visual asset tests; expect missing resolver failure.
- [ ] Implement `resolve_visual_assets(plan, work_dir, editing)` with injected provider seams and store source/effect/duration/path metadata in pipeline state.
- [ ] Wire `cmd_produce` to normalize the draft plan and resolve it instead of flattening all output into three frames.
- [ ] Re-run visual asset and main tests; expect pass.

### Task 6: Timeline Effects And Duration Normalization

**Files:**
- Modify: `verticals/broll.py`
- Modify: `verticals/assemble.py`
- Modify: `tests/test_assemble.py`
- Modify: `tests/test_broll.py`

- [ ] Write failing tests asserting punch-zoom and shake ffmpeg filters are generated and that timeline durations cycle/trim to equal a supplied voiceover duration.
- [ ] Run assembly and b-roll tests; expect missing effect/timeline behavior failures.
- [ ] Add `punch_zoom`, `shake`, `pan`, and `hard_cut` effect handling. Add `normalize_timeline_duration(items, duration)` and make assembly use per-item durations/effects while preserving legacy `frames` input.
- [ ] Re-run assembly and b-roll tests; expect pass.

### Task 7: Backend State And Verification

**Files:**
- Modify: `verticals/server.py`
- Modify: `tests/test_server.py`
- Modify: `.env.example` if present
- Modify: `README.md`

- [ ] Write a failing server test asserting completed job results expose visual provider counts without credentials.
- [ ] Run server tests; expect missing summary failure.
- [ ] Persist and return only `visual_summary` counts, document `IMGFLIP_USERNAME` and `IMGFLIP_PASSWORD`, and retain all existing request shapes.
- [ ] Run focused tests for niche, draft, visual plan, b-roll, Imgflip, assets, assembly, main, and server.
- [ ] Run `.venv\Scripts\python.exe -m pytest -q`; expect zero failures.
- [ ] Run `.venv\Scripts\python.exe -m compileall -q verticals tests`; expect exit code 0.

