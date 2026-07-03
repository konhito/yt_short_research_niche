"""Quality filters for harvested assets."""

from __future__ import annotations

from typing import Any


def evaluate_asset_quality(asset: dict[str, Any]) -> dict[str, Any]:
    """Score and gate media assets before semantic matching."""
    width = int(asset.get("width", 0) or 0)
    height = int(asset.get("height", 0) or 0)
    is_vertical = bool(asset.get("is_vertical", height >= width if width and height else False))
    watermark_score = float(asset.get("watermark_score", 0.0) or 0.0)
    duplicate_score = float(asset.get("duplicate_score", 0.0) or 0.0)
    talking_head_score = float(asset.get("talking_head_score", 0.0) or 0.0)
    compilation_score = float(asset.get("compilation_score", 0.0) or 0.0)

    reasons: list[str] = []
    quality_score = 1.0

    if watermark_score >= 0.7:
        reasons.append("watermark")
        quality_score -= 0.4
    if duplicate_score >= 0.8:
        reasons.append("duplicate")
        quality_score -= 0.5
    if width and height and width > height:
        reasons.append("landscape")
        quality_score -= 0.15
    if min(width, height) and min(width, height) < 720:
        reasons.append("low_resolution")
        quality_score -= 0.2
    if talking_head_score >= 0.75:
        reasons.append("talking_head")
        quality_score -= 0.2
    if compilation_score >= 0.75:
        reasons.append("compilation")
        quality_score -= 0.2
    if not is_vertical and "landscape" not in reasons and width and height:
        reasons.append("not_vertical")
        quality_score -= 0.1

    quality_score = max(0.0, min(1.0, quality_score))
    accepted = not any(reason in {"watermark", "duplicate"} for reason in reasons)
    if width and height and width > height and max(width, height) >= 1440:
        accepted = False
    return {
        "accepted": accepted,
        "reasons": reasons,
        "quality_score": quality_score,
        "is_vertical": is_vertical,
    }
