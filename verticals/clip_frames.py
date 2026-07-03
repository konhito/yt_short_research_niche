"""Extract representative frames for visual clip review."""

from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image, ImageDraw

from .config import run_cmd

SAMPLE_RATIOS = (0.08, 0.24, 0.40, 0.56, 0.72, 0.88)


def sample_timestamps(duration: float) -> list[float]:
    """Return stable review positions away from intros and end cards."""
    duration = max(0.0, float(duration))
    return [round(duration * ratio, 3) for ratio in SAMPLE_RATIOS]


def sample_clip_frames(candidate: dict, out_dir: Path) -> dict:
    """Attach six sampled frames and a labelled contact sheet to a candidate."""
    clip = Path(candidate["path"])
    duration = float(candidate.get("actual_duration") or candidate.get("duration") or 0)
    if duration <= 0:
        from .video_candidates import probe_video

        duration = float(probe_video(clip).get("actual_duration") or 0)
    if duration <= 0:
        raise ValueError(f"Cannot sample clip without duration: {clip}")

    identity = str(candidate.get("source_id") or candidate.get("media_hash") or clip.stem)
    path_digest = hashlib.sha1(str(clip.resolve()).lower().encode("utf-8")).hexdigest()[:10]
    clip_id = f"{candidate.get('source', 'video')}_{identity}_{path_digest}"
    sample_dir = out_dir / _safe_name(clip_id)
    sample_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for index, (ratio, timestamp) in enumerate(zip(SAMPLE_RATIOS, sample_timestamps(duration)), 1):
        output = sample_dir / f"frame_{index:02d}.jpg"
        _extract_frame(clip, timestamp, output)
        records.append({
            "path": str(output),
            "timestamp_seconds": timestamp,
            "position_ratio": ratio,
        })

    sheet_path = sample_dir / "contact_sheet.jpg"
    _create_contact_sheet(records, sheet_path)
    return {
        **candidate,
        "sampled_frames": records,
        "review_contact_sheet_path": str(sheet_path),
    }


def _extract_frame(clip: Path, timestamp: float, output: Path) -> None:
    run_cmd([
        "ffmpeg", "-ss", str(timestamp), "-i", str(clip), "-frames:v", "1",
        "-vf", "scale=360:-2", "-q:v", "3", "-y", "-loglevel", "quiet", str(output),
    ], timeout=30)


def _create_contact_sheet(records: list[dict], output: Path) -> None:
    tiles = []
    for record in records:
        with Image.open(record["path"]) as source:
            image = source.convert("RGB")
            image.thumbnail((360, 360), Image.Resampling.LANCZOS)
            tile = Image.new("RGB", (360, image.height + 28), "black")
            tile.paste(image, ((360 - image.width) // 2, 0))
            ImageDraw.Draw(tile).text(
                (8, image.height + 6),
                f"{record['timestamp_seconds']:.2f}s",
                fill="white",
            )
            tiles.append(tile)

    row_height = max(tile.height for tile in tiles)
    sheet = Image.new("RGB", (1080, row_height * 2), "black")
    for index, tile in enumerate(tiles):
        sheet.paste(tile, ((index % 3) * 360, (index // 3) * row_height))
    sheet.save(output, quality=88)


def _safe_name(value: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "-_" else "_" for char in value)
    return cleaned[:80] or "clip"
