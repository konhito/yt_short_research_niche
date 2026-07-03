"""Inspect downloaded media and attach editor-facing metadata."""

from __future__ import annotations

from pathlib import Path


def inspect_media_file(path: Path) -> dict:
    """Return stable metadata for a downloaded media file."""
    path = Path(path)
    metadata = probe_video(path)
    contact_sheet_path = path.with_name("contact_sheet.jpg")
    try:
        create_contact_sheet(path, metadata.get("actual_duration", 0.0), contact_sheet_path)
        contact_value = str(contact_sheet_path)
    except Exception:
        contact_value = ""
    return {
        "path": str(path),
        "media_hash": hash_file(path),
        "width": int(metadata.get("width", 0)),
        "height": int(metadata.get("height", 0)),
        "actual_duration": float(metadata.get("actual_duration", 0.0)),
        "is_vertical": bool(metadata.get("is_vertical", False)),
        "contact_sheet_path": contact_value,
    }


def probe_video(path: Path) -> dict:
    from .video_candidates import probe_video as _probe_video

    return _probe_video(path)


def hash_file(path: Path) -> str:
    from .video_candidates import hash_file as _hash_file

    return _hash_file(path)


def create_contact_sheet(path: Path, duration: float, out_path: Path) -> Path:
    from .video_candidates import create_contact_sheet as _create_contact_sheet

    return _create_contact_sheet(path, duration, out_path)
