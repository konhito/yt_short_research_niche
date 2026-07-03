"""AI editor timeline planning and validation."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .log import log

ALLOWED_EFFECTS = {"punch_zoom", "pan", "pan_right", "shake", "hard_cut", "zoom_in", "zoom_out"}
ALLOWED_FITS = {"cover_crop", "fit_width_pad", "contain_pad"}


def build_asset_manifest(assets: list[dict]) -> list[dict]:
    """Create stable ids and editor-facing metadata for resolved assets."""
    manifest = []
    for index, asset in enumerate(assets, 1):
        path = str(asset.get("path", ""))
        kind = asset.get("type") or _infer_kind(path)
        fit = asset.get("fit")
        if not fit:
            fit = "fit_width_pad" if kind == "meme" or asset.get("source") == "imgflip" else "cover_crop"
        manifest.append({
            "asset_id": f"asset_{index:03d}",
            "path": path,
            "filename": Path(path).name if path else "",
            "type": kind,
            "source": asset.get("source", kind),
            "query": asset.get("query", ""),
            "effect": asset.get("effect", "pan"),
            "fit": fit,
            "duration_seconds": float(asset.get("duration_seconds", 3.0)),
            "template_hint": asset.get("template_hint", ""),
            "meme_text_top": asset.get("meme_text_top", ""),
            "meme_text_bottom": asset.get("meme_text_bottom", ""),
            "meme_template_id": asset.get("meme_template_id", ""),
            "meme_template_name": asset.get("meme_template_name", ""),
            "protected": bool(asset.get("protected")),
            "asset_role": asset.get("asset_role", ""),
            "title": asset.get("title", ""),
            "url": asset.get("url", ""),
            "uploader": asset.get("uploader", ""),
            "relevance_score": asset.get("relevance_score", 0),
            "status": asset.get("status", ""),
            "subreddit": asset.get("subreddit", ""),
            "contact_sheet_path": asset.get("contact_sheet_path", ""),
            "actual_duration": float(asset.get("actual_duration") or asset.get("duration") or 0),
            "media_hash": asset.get("media_hash", ""),
        })
    return manifest


def create_editor_timeline(
    *,
    draft: dict,
    transcript_words: list[dict],
    assets: list[dict],
    music_plan: dict | None,
    duration: float,
    editing: dict,
    provider: str = "openai",
) -> list[dict]:
    """Ask an LLM to act as editor; fall back to deterministic no-loop plan."""
    manifest = build_asset_manifest(assets)
    if not manifest:
        return []
    prompt = _build_editor_prompt(draft, transcript_words, manifest, music_plan or {}, duration, editing)
    try:
        from .llm import call_llm

        text = call_llm(prompt, provider=provider, max_tokens=2500)
        payload = _extract_json(text)
        timeline = validate_editor_timeline(payload.get("timeline", []), manifest, duration, editing)
        if timeline:
            _log_timeline_summary(timeline, duration)
            log(f"Editor brain produced {len(timeline)} timeline cuts")
            return timeline
        log("Editor brain returned no valid cuts - using fallback timeline")
    except Exception as exc:
        log(f"Editor brain failed ({exc}) - using fallback timeline")
    timeline = build_fallback_editor_timeline(manifest, duration, editing)
    _log_timeline_summary(timeline, duration)
    return timeline


def validate_editor_timeline(
    raw_timeline: list[dict],
    assets: list[dict],
    duration: float,
    editing: dict | None = None,
) -> list[dict]:
    """Validate and normalize editor output.

    Repeated assets are dropped unless the editor provides a reuse_reason.
    """
    by_id = {asset["asset_id"]: asset for asset in assets}
    used: set[str] = set()
    used_meme_paths: set[str] = set()
    used_meme_templates: set[str] = set()
    result = []
    cursor = 0.0
    allowed_effects = set((editing or {}).get("effects") or ALLOWED_EFFECTS) | ALLOWED_EFFECTS
    fill_color = _fill_color(editing or {})
    for item in raw_timeline:
        if not isinstance(item, dict):
            continue
        asset_id = str(item.get("asset_id", ""))
        asset = by_id.get(asset_id)
        if not asset:
            continue
        reuse_reason = str(item.get("reuse_reason", "")).strip()
        if asset_id in used and not reuse_reason:
            continue
        if asset.get("source") == "imgflip" and asset.get("path") in used_meme_paths and not reuse_reason:
            continue
        if asset.get("source") == "imgflip" and asset.get("meme_template_id") in used_meme_templates and not reuse_reason:
            continue
        start = _float(item.get("start"), cursor)
        end = _float(item.get("end"), start + _float(item.get("duration_seconds"), asset["duration_seconds"]))
        start = max(0.0, min(start, duration))
        end = max(start + 0.25, min(end, duration))
        if end <= start or start >= duration:
            continue
        effect = str(item.get("effect") or asset.get("effect") or "pan")
        if effect not in allowed_effects:
            effect = "pan"
        fit = str(item.get("fit") or asset.get("fit") or "cover_crop")
        if fit not in ALLOWED_FITS:
            fit = "cover_crop"
        normalized = {
            **asset,
            "start": round(start, 3),
            "end": round(end, 3),
            "duration_seconds": round(end - start, 3),
            "effect": effect,
            "fit": fit,
            "fill_color": str(item.get("fill_color") or fill_color),
            "caption_emphasis": str(item.get("caption_emphasis", "")),
        }
        source_start = max(0.0, _float(item.get("source_start_seconds"), 0.0))
        actual_duration = float(asset.get("actual_duration") or 0)
        if actual_duration > 0:
            source_start = min(source_start, max(0.0, actual_duration - (end - start)))
        normalized["source_start_seconds"] = round(source_start, 3)
        if reuse_reason:
            normalized["reuse_reason"] = reuse_reason
        result.append(normalized)
        used.add(asset_id)
        if asset.get("source") == "imgflip":
            used_meme_paths.add(str(asset.get("path", "")))
            if asset.get("meme_template_id"):
                used_meme_templates.add(str(asset["meme_template_id"]))
        cursor = end
    for asset in assets:
        if asset.get("protected") and asset["asset_id"] not in used:
            result.append({
                **asset,
                "start": cursor,
                "end": min(duration, cursor + float(asset.get("duration_seconds", 3.0))),
                "duration_seconds": float(asset.get("duration_seconds", 3.0)),
                "effect": asset.get("effect", "pan"),
                "fit": asset.get("fit", "cover_crop"),
                "fill_color": fill_color,
                "caption_emphasis": "protected original b-roll prompt",
            })
            used.add(asset["asset_id"])
            cursor = result[-1]["end"]
    source_targets = _source_targets(editing or {})
    for source, target in source_targets.items():
        selected = sum(item.get("source") == source for item in result)
        for asset in assets:
            if selected >= target["minimum"]:
                break
            if asset.get("source") != source or asset["asset_id"] in used:
                continue
            if source == "imgflip" and asset.get("path") in used_meme_paths:
                continue
            if source == "imgflip" and asset.get("meme_template_id") in used_meme_templates:
                continue
            result.append({
                **asset,
                "start": cursor,
                "end": cursor + float(asset.get("duration_seconds", 3.0)),
                "duration_seconds": float(asset.get("duration_seconds", 3.0)),
                "effect": asset.get("effect", "hard_cut"),
                "fit": asset.get("fit", "cover_crop"),
                "fill_color": fill_color,
                "caption_emphasis": f"minimum {source} source target",
                "source_start_seconds": 0.0,
            })
            used.add(asset["asset_id"])
            if source == "imgflip":
                used_meme_paths.add(str(asset.get("path", "")))
                if asset.get("meme_template_id"):
                    used_meme_templates.add(str(asset["meme_template_id"]))
            cursor = result[-1]["end"]
            selected += 1
    return _retime_to_duration(result, duration)


def build_fallback_editor_timeline(
    assets: list[dict],
    duration: float,
    editing: dict | None = None,
) -> list[dict]:
    """Create a non-repeating timeline using each asset once."""
    if not assets or duration <= 0:
        return []
    fill_color = _fill_color(editing or {})
    segment = duration / len(assets)
    timeline = []
    elapsed = 0.0
    for index, asset in enumerate(assets):
        end = duration if index == len(assets) - 1 else elapsed + segment
        effect = asset.get("effect", "pan")
        fit = asset.get("fit", "cover_crop")
        timeline.append({
            **asset,
            "start": round(elapsed, 3),
            "end": round(end, 3),
            "duration_seconds": round(end - elapsed, 3),
            "effect": effect if effect in ALLOWED_EFFECTS else "pan",
            "fit": fit if fit in ALLOWED_FITS else "cover_crop",
            "fill_color": fill_color,
            "caption_emphasis": "",
        })
        elapsed = end
    return timeline


def _retime_to_duration(timeline: list[dict], duration: float) -> list[dict]:
    if not timeline or duration <= 0:
        return timeline
    total = sum(max(0.25, float(item.get("duration_seconds", 0.25))) for item in timeline)
    if total <= 0:
        return timeline
    cursor = 0.0
    retimed = []
    for index, item in enumerate(timeline):
        if index == len(timeline) - 1:
            end = duration
        else:
            segment = max(0.25, float(item.get("duration_seconds", 0.25))) / total * duration
            end = min(duration, cursor + segment)
        retimed.append({
            **item,
            "start": round(cursor, 3),
            "end": round(end, 3),
            "duration_seconds": round(end - cursor, 3),
        })
        cursor = end
    return retimed


def _build_editor_prompt(
    draft: dict,
    transcript_words: list[dict],
    assets: list[dict],
    music_plan: dict,
    duration: float,
    editing: dict,
) -> str:
    script = draft.get("script", "")
    transcript_sample = transcript_words[:220]
    transcript_segments = _transcript_segments(transcript_words)
    source_targets = _source_targets(editing)
    payload = {
        "job": {
            "title": draft.get("youtube_title", ""),
            "niche": draft.get("niche", "general"),
            "duration_seconds": duration,
            "editing_style": editing.get("style", "balanced"),
        },
        "script": script,
        "transcript_words": transcript_sample,
        "transcript_segments": transcript_segments,
        "assets": assets,
        "music_plan": music_plan,
        "source_targets": source_targets,
        "rules": [
            "Return JSON only. No markdown.",
            "Use every asset at most once unless reuse_reason explains the callback.",
            "Cover the full audio duration with start/end seconds.",
            "Put meme assets on shock, joke, or reaction beats.",
            "Use more youtube_harvest and meme assets than stock footage when relevant.",
            "Place youtube_harvest clips near transcript segments with matching topic words.",
            "Place memes near transcript segments with surprise, backlash, chaos, joke, or hot-take wording.",
            "Use fit_width_pad for meme assets so they keep their original aspect ratio.",
            "Use fast cuts early; make the first 3 seconds visually intense.",
            "For harvested videos return source_start_seconds for the best visual moment.",
        ],
        "allowed_effects": sorted(ALLOWED_EFFECTS),
        "allowed_fits": sorted(ALLOWED_FITS),
        "schema": {
            "timeline": [{
                "asset_id": "asset_001",
                "start": 0.0,
                "end": 2.7,
                "effect": "punch_zoom",
                "fit": "cover_crop",
                "caption_emphasis": "short reason for this cut",
                "source_start_seconds": 0.0,
                "reuse_reason": "optional; required if asset_id repeats",
            }]
        },
    }
    return "You are a ruthless short-form video editor. Build a detailed edit timeline.\n" + json.dumps(
        payload,
        ensure_ascii=False,
    )


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    if fenced:
        cleaned = fenced.group(1)
    return json.loads(cleaned)


def _transcript_segments(words: list[dict], group_size: int = 12) -> list[dict]:
    segments = []
    for index in range(0, len(words), group_size):
        group = words[index:index + group_size]
        if not group:
            continue
        text = " ".join(str(item.get("word", "")).strip() for item in group).strip()
        if not text:
            continue
        segments.append({
            "start": float(group[0].get("start", 0)),
            "end": float(group[-1].get("end", group[0].get("start", 0))),
            "text": text,
        })
    return segments[:40]


def _source_targets(editing: dict) -> dict[str, dict[str, int]]:
    mapping = {
        "youtube_harvest": editing.get("youtube_clips", [0, 0]),
        "reddit_harvest": editing.get("reddit_clips", [0, 0]),
        "web_research": editing.get("research_images", [0, 0]),
        "imgflip": editing.get("meme_beats", [0, 0]),
        "openai": editing.get("ai_images", [0, 0]),
    }
    return {
        source: {"minimum": int(values[0]), "maximum": int(values[1])}
        for source, values in mapping.items()
        if isinstance(values, (list, tuple)) and len(values) == 2
    }


def _infer_kind(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".mp4", ".mov", ".m4v", ".webm", ".mkv"}:
        return "pexels"
    return "ai_image"


def _float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _fill_color(editing: dict) -> str:
    return str(editing.get("meme_fill_color") or editing.get("fill_color") or "#0D0D0D")


def _log_timeline_summary(timeline: list[dict], duration: float):
    counts = {}
    for item in timeline:
        key = item.get("source") or item.get("type") or "unknown"
        counts[key] = counts.get(key, 0) + 1
    end = timeline[-1]["end"] if timeline else 0
    log(f"Editor timeline mix: {counts}; coverage={end:.1f}/{duration:.1f}s")
