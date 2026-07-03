"""Match script beats to the strongest asset candidates."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .vision_review import score_asset_relevance


def match_assets_to_beats(beats: list[dict[str, Any]], assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Rank assets for each beat and pick the best available one."""
    result = []
    used_assets: set[str] = set()
    for beat_index, beat in enumerate(beats):
        ranked = []
        for asset in assets:
            scored = deepcopy(asset)
            score = score_asset_relevance(beat, scored)
            reuse_penalty = 0.18 if str(scored.get("asset_id", "")) in used_assets else 0.0
            scored["reuse_penalty"] = reuse_penalty
            scored["combined_score"] = max(0.0, min(1.0, score["combined_score"] - reuse_penalty))
            scored.update(score)
            ranked.append(scored)
        ranked.sort(key=lambda item: item.get("combined_score", 0.0), reverse=True)
        selected = ranked[0] if ranked else None
        if selected and selected.get("asset_id"):
            used_assets.add(str(selected["asset_id"]))
        result.append({
            **beat,
            "ranked_assets": ranked,
            "selected_asset": selected,
        })
    return result
