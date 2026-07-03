"""Vision review for harvested video candidates."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import requests

from .config import get_openai_key
from .clip_frames import sample_clip_frames
from .log import log

ALLOWED_WARNINGS = {
    "watermark", "unrelated_captions", "talking_head", "duplicate",
    "low_resolution", "wrong_topic",
}
VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def is_reviewable_video(candidate: dict) -> bool:
    return Path(str(candidate.get("path", ""))).suffix.lower() in VIDEO_SUFFIXES


def prepare_video_candidates_for_review(
    draft: dict,
    transcript_words: list[dict],
    candidates: list[dict],
    out_dir: Path,
    *,
    workers: int = 4,
    batch_size: int = 4,
    keep_threshold: float = 0.58,
) -> dict[str, Any]:
    """Sample downloaded candidates concurrently, then run visual review."""
    sampled: list[dict | None] = [None] * len(candidates)
    with ThreadPoolExecutor(max_workers=max(1, min(8, workers))) as executor:
        futures = {
            executor.submit(sample_clip_frames, candidate, out_dir / "frames"): index
            for index, candidate in enumerate(candidates)
        }
        for future in as_completed(futures):
            index = futures[future]
            try:
                sampled[index] = future.result()
            except Exception as exc:
                sampled[index] = {**candidates[index], "frame_sampling_error": str(exc)}
                log(f"Clip frame sampling failed for {_candidate_id(candidates[index])}: {exc}")
    return review_video_candidates(
        draft,
        transcript_words,
        [item for item in sampled if item is not None],
        out_dir,
        batch_size=batch_size,
        keep_threshold=keep_threshold,
    )


def review_video_candidates(
    draft: dict,
    transcript_words: list[dict],
    candidates: list[dict],
    out_dir: Path,
    *,
    batch_size: int = 4,
    keep_threshold: float = 0.58,
) -> dict[str, Any]:
    """Review candidates in isolated batches and persist all decisions."""
    out_dir.mkdir(parents=True, exist_ok=True)
    reviewed = []
    fallback_count = 0
    for offset in range(0, len(candidates), max(1, batch_size)):
        batch = candidates[offset:offset + max(1, batch_size)]
        visual_batch = []
        for candidate in batch:
            sheet = Path(str(candidate.get("review_contact_sheet_path") or candidate.get("contact_sheet_path") or ""))
            if sheet.is_file():
                visual_batch.append(candidate)
            else:
                reviewed.append(_metadata_fallback(candidate, keep_threshold, "contact sheet unavailable"))
                fallback_count += 1
        if not visual_batch:
            continue
        try:
            payload = call_openai_clip_review(
                visual_batch,
                draft=draft,
                transcript_words=transcript_words,
            )
            by_id = {
                str(item.get("asset_id", "")): item
                for item in payload.get("clips", [])
                if isinstance(item, dict)
            }
            for candidate in visual_batch:
                candidate_id = _candidate_id(candidate)
                raw = by_id.get(candidate_id)
                if raw is None:
                    reviewed.append(_metadata_fallback(candidate, keep_threshold, "missing model decision"))
                    fallback_count += 1
                else:
                    reviewed.append(validate_review_decision(candidate, raw, keep_threshold))
        except Exception as exc:
            log(f"Clip vision review batch failed ({exc}) - using metadata fallback")
            reviewed.extend(_metadata_fallback(item, keep_threshold, str(exc)) for item in visual_batch)
            fallback_count += len(visual_batch)

    approved = [item for item in reviewed if item["review_decision"] == "keep"]
    discarded = [item for item in reviewed if item["review_decision"] == "discard"]
    manifest = {
        "approved": approved,
        "discarded": discarded,
        "reviewed_count": len(reviewed),
        "fallback_count": fallback_count,
    }
    manifest_path = out_dir / "clip_review_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    source_counts: dict[str, dict[str, int]] = {}
    for item in reviewed:
        source = str(item.get("source") or "unknown")
        counts = source_counts.setdefault(source, {"kept": 0, "discarded": 0})
        counts["kept" if item["review_decision"] == "keep" else "discarded"] += 1
    log(
        f"Clip review: reviewed={len(reviewed)} kept={len(approved)} "
        f"discarded={len(discarded)} fallback={fallback_count} sources={source_counts}"
    )
    return {**manifest, "manifest_path": str(manifest_path), "source_counts": source_counts}


def validate_review_decision(candidate: dict, raw: dict, keep_threshold: float = 0.58) -> dict:
    """Validate untrusted model output against candidate identity and duration."""
    duration = max(0.0, float(candidate.get("actual_duration") or candidate.get("duration") or 0))
    relevance = _clamp_score(raw.get("relevance_score"))
    quality = _clamp_score(raw.get("quality_score", candidate.get("quality_score", 0)))
    warnings = [
        str(item) for item in raw.get("warnings", [])
        if str(item) in ALLOWED_WARNINGS
    ]
    ranges = _validated_ranges(raw.get("useful_ranges", []), duration)
    requested_keep = str(raw.get("decision", "discard")).lower() == "keep"
    decision = "keep" if requested_keep and relevance >= keep_threshold and "wrong_topic" not in warnings else "discard"
    if decision == "keep" and not ranges and duration > 0:
        timestamp = _best_sample_timestamp(candidate, duration)
        start = max(0.0, timestamp - 1.5)
        end = min(duration, max(start + 0.75, timestamp + 1.5))
        ranges = [{"start": round(start, 3), "end": round(end, 3), "reason": "sampled visual"}]
    return {
        **candidate,
        "review_decision": decision,
        "review_mode": "openai_vision",
        "review_reason": str(raw.get("reason", "")).strip(),
        "vision_relevance_score": relevance,
        "vision_quality_score": quality,
        "visual_description": str(raw.get("visual_description", "")).strip(),
        "matched_beat_ids": [str(item) for item in raw.get("matched_beat_ids", []) if str(item).strip()],
        "approved_source_ranges": ranges,
        "review_warnings": warnings,
    }


def call_openai_clip_review(batch: list[dict], *, draft: dict, transcript_words: list[dict]) -> dict:
    """Send contact sheets and story context to an OpenAI vision model."""
    api_key = get_openai_key()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not set")
    context = {
        "title": draft.get("youtube_title", ""),
        "script": draft.get("script", ""),
        "script_beats": draft.get("script_beats", []),
        "transcript_segments": _transcript_segments(transcript_words),
        "candidates": [
            {
                "asset_id": _candidate_id(item),
                "source": item.get("source", ""),
                "title": item.get("title", ""),
                "query": item.get("search_query") or item.get("query", ""),
                "duration": item.get("actual_duration") or item.get("duration", 0),
                "sampled_frames": item.get("sampled_frames", []),
            }
            for item in batch
        ],
    }
    instructions = (
        "Review every contact sheet against the story and transcript. Return JSON only with a clips array. "
        "For each asset_id return decision keep/discard, relevance_score and quality_score from 0 to 1, "
        "reason, visual_description, matched_beat_ids, useful_ranges with start/end/reason, and warnings. "
        "Use wrong_topic when visuals concern a different subject. Prefer precise useful moments over intros.\n"
        + json.dumps(context, ensure_ascii=False)
    )
    content: list[dict] = [{"type": "text", "text": instructions}]
    for item in batch:
        sheet = Path(str(item.get("review_contact_sheet_path") or item.get("contact_sheet_path") or ""))
        if not sheet.exists():
            continue
        content.append({"type": "text", "text": f"Contact sheet for asset_id={_candidate_id(item)}"})
        content.append({
            "type": "image_url",
            "image_url": {"url": _data_url(sheet), "detail": "low"},
        })
    response = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": os.environ.get("OPENAI_VISION_MODEL", "gpt-4o-mini"),
            "temperature": 0.1,
            "max_tokens": 2400,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content}],
        },
        timeout=120,
    )
    if response.status_code != 200:
        raise RuntimeError(f"OpenAI vision API {response.status_code}: {response.text[:300]}")
    text = response.json()["choices"][0]["message"]["content"]
    payload = json.loads(text)
    if not isinstance(payload, dict) or not isinstance(payload.get("clips"), list):
        raise ValueError("OpenAI vision response missing clips array")
    return payload


def _metadata_fallback(candidate: dict, threshold: float, reason: str) -> dict:
    relevance = _clamp_score(float(candidate.get("relevance_score", 0) or 0) / 30.0)
    accepted = bool(candidate.get("accepted", True))
    decision = "keep" if accepted and relevance >= threshold else "discard"
    duration = float(candidate.get("actual_duration") or candidate.get("duration") or 0)
    ranges = []
    if decision == "keep" and duration > 0:
        ranges = [{"start": 0.0, "end": round(duration, 3), "reason": "metadata fallback"}]
    return {
        **candidate,
        "review_decision": decision,
        "review_mode": "metadata_fallback",
        "review_reason": reason,
        "vision_relevance_score": relevance,
        "vision_quality_score": _clamp_score(candidate.get("quality_score", 0)),
        "visual_description": "",
        "matched_beat_ids": [],
        "approved_source_ranges": ranges,
        "review_warnings": [],
    }


def _validated_ranges(raw_ranges: Any, duration: float) -> list[dict]:
    result = []
    for item in raw_ranges if isinstance(raw_ranges, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            start = max(0.0, min(float(item.get("start", 0)), duration))
            end = max(0.0, min(float(item.get("end", 0)), duration))
        except (TypeError, ValueError):
            continue
        if end - start < 0.75:
            continue
        if result and start < result[-1]["end"]:
            continue
        result.append({
            "start": round(start, 3),
            "end": round(end, 3),
            "reason": str(item.get("reason", "")).strip(),
        })
    return result


def _candidate_id(candidate: dict) -> str:
    return str(candidate.get("source_id") or candidate.get("media_hash") or Path(candidate.get("path", "clip")).stem)


def _clamp_score(value: Any) -> float:
    try:
        return round(max(0.0, min(1.0, float(value))), 4)
    except (TypeError, ValueError):
        return 0.0


def _best_sample_timestamp(candidate: dict, duration: float) -> float:
    frames = candidate.get("sampled_frames") or []
    if frames:
        try:
            return max(0.0, min(duration, float(frames[len(frames) // 2].get("timestamp_seconds", duration / 2))))
        except (TypeError, ValueError):
            pass
    return duration / 2


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _transcript_segments(words: list[dict], size: int = 12) -> list[dict]:
    segments = []
    for offset in range(0, len(words), size):
        group = words[offset:offset + size]
        if not group:
            continue
        segments.append({
            "start": float(group[0].get("start", 0)),
            "end": float(group[-1].get("end", 0)),
            "text": " ".join(str(item.get("word", "")).strip() for item in group).strip(),
        })
    return segments[:40]
