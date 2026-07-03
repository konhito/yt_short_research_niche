"""Shared harvested-video candidate helpers."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from PIL import Image

from .config import run_cmd


def normalize_candidate(raw: dict) -> dict:
    """Normalize platform-specific metadata for the editor and assembler."""
    return {
        **raw,
        "type": "harvested_video",
        "status": raw.get("status", "candidate"),
        "protected": bool(raw.get("protected", True)),
        "asset_role": raw.get("asset_role", "harvested_video"),
        "effect": raw.get("effect", "hard_cut"),
        "fit": raw.get("fit", "cover_crop"),
    }


def deduplicate_candidates(items: list[dict]) -> list[dict]:
    """Keep the highest-scored candidate for each file/media URL/source URL."""
    best: dict[str, dict] = {}
    unkeyed = []
    for item in items:
        key = str(item.get("media_hash") or item.get("media_url") or item.get("url") or "")
        if not key:
            unkeyed.append(item)
            continue
        current = best.get(key)
        if current is None or item.get("relevance_score", 0) > current.get("relevance_score", 0):
            best[key] = item
    result = list(best.values()) + unkeyed
    return sorted(result, key=lambda item: item.get("relevance_score", 0), reverse=True)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def probe_video(path: Path) -> dict:
    try:
        result = run_cmd(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_streams", "-show_format", str(path),
            ],
            capture=True,
        )
        payload = json.loads(result.stdout)
        stream = next((item for item in payload.get("streams", []) if item.get("width") and item.get("height")), {})
        width = int(stream.get("width") or 0)
        height = int(stream.get("height") or 0)
        duration = float(payload.get("format", {}).get("duration") or stream.get("duration") or 0)
    except Exception:
        result = run_cmd(["ffmpeg", "-i", str(path)], capture=True, check=False)
        stderr = result.stderr or ""
        duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
        dimension_match = re.search(r"\b(\d{2,5})x(\d{2,5})\b", stderr)
        if not duration_match or not dimension_match:
            raise RuntimeError(f"Unable to probe video metadata: {path}")
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        width, height = (int(value) for value in dimension_match.groups())
    return {
        "width": width,
        "height": height,
        "actual_duration": duration,
        "is_vertical": bool(width and height and height >= width),
    }


def create_contact_sheet(path: Path, duration: float, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames = []
    for index, ratio in enumerate((0.2, 0.5, 0.8)):
        frame = out_path.parent / f"contact_{index}.jpg"
        run_cmd([
            "ffmpeg", "-ss", str(max(0.0, duration * ratio)), "-i", str(path),
            "-frames:v", "1", "-vf", "scale=360:-2", "-y", "-loglevel", "quiet", str(frame),
        ])
        frames.append(frame)
    images = [Image.open(frame).convert("RGB") for frame in frames]
    target_height = min(image.height for image in images)
    resized = [
        image.resize((max(1, int(image.width * target_height / image.height)), target_height), Image.LANCZOS)
        for image in images
    ]
    sheet = Image.new("RGB", (sum(image.width for image in resized), target_height), "black")
    x = 0
    for image in resized:
        sheet.paste(image, (x, 0))
        x += image.width
    sheet.save(out_path, quality=88)
    for frame in frames:
        frame.unlink(missing_ok=True)
    return out_path


def enrich_candidate(candidate: dict) -> dict:
    path = Path(candidate["path"])
    metadata = probe_video(path)
    contact_path = path.parent / "contact_sheet.jpg"
    try:
        create_contact_sheet(path, metadata["actual_duration"], contact_path)
        contact_value = str(contact_path)
    except Exception:
        contact_value = ""
    return {
        **candidate,
        **metadata,
        "media_hash": hash_file(path),
        "contact_sheet_path": contact_value,
    }
