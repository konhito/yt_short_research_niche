"""Validation rules for semantic editor timelines."""

from __future__ import annotations

from typing import Any


def validate_semantic_timeline(timeline: list[dict[str, Any]], duration: float) -> dict[str, Any]:
    """Validate final cut ordering, repetition, and coverage."""
    errors: list[str] = []
    warnings: list[str] = []
    repairs: list[str] = []

    seen_assets: set[str] = set()
    first_asset = None
    covered = 0.0
    for index, item in enumerate(timeline):
        asset_id = str(item.get("asset_id", "")).strip()
        if not asset_id:
            errors.append(f"item {index + 1} missing asset_id")
            continue
        if index == 0:
            first_asset = asset_id
        elif asset_id == first_asset:
            errors.append("repeated asset in opening timeline")
        if asset_id in seen_assets and not item.get("reuse_reason"):
            errors.append(f"repeated asset without callback: {asset_id}")
        seen_assets.add(asset_id)
        covered = max(covered, float(item.get("end", 0.0) or 0.0))

    if duration > 0 and covered < duration * 0.95:
        warnings.append(f"coverage short: {covered:.2f}/{duration:.2f}s")
        errors.append("coverage too short")
    if not timeline:
        errors.append("empty timeline")

    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "repairs": repairs,
    }
