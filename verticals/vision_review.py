"""Vision-style relevance scoring for script beats and assets."""

from __future__ import annotations

import re
from typing import Any


def score_asset_relevance(beat: dict[str, Any], asset: dict[str, Any]) -> dict[str, Any]:
    """Combine semantic, entity, visual, quality, and freshness signals."""
    beat_text = " ".join(
        str(beat.get(key, ""))
        for key in ("script_text", "visual_description")
    ).lower()
    beat_entities = {str(item).lower() for item in beat.get("entities", []) if str(item).strip()}
    asset_text = " ".join(
        str(asset.get(key, ""))
        for key in ("title", "query", "search_query", "topic_query", "url")
    ).lower()
    asset_labels = _expanded_terms(asset.get("vision_labels", []))

    semantic_score = _overlap_score(_tokens(beat_text), _tokens(asset_text))
    entity_score = _overlap_score(beat_entities, _tokens(asset_text) | asset_labels)
    visual_score = _overlap_score(_tokens(beat_text), asset_labels)
    quality_score = float(asset.get("quality_score", 0.0) or 0.0)
    freshness_score = max(0.0, min(1.0, 1.0 - float(asset.get("freshness_penalty", 0.0) or 0.0)))
    reuse_penalty = max(0.0, float(asset.get("reuse_penalty", 0.0) or 0.0))

    combined_score = (
        0.40 * semantic_score
        + 0.20 * entity_score
        + 0.15 * visual_score
        + 0.15 * quality_score
        + 0.10 * freshness_score
        - reuse_penalty
    )
    combined_score = max(0.0, min(1.0, combined_score))
    return {
        "semantic_score": semantic_score,
        "entity_score": entity_score,
        "visual_score": visual_score,
        "quality_score": quality_score,
        "freshness_score": freshness_score,
        "reuse_penalty": reuse_penalty,
        "combined_score": combined_score,
    }


def _tokens(text: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 2
    }


def _expanded_terms(values: list[Any]) -> set[str]:
    terms: set[str] = set()
    for value in values:
        text = str(value).strip().lower()
        if not text:
            continue
        terms.add(text)
        terms.update(_tokens(text))
    return terms


def _overlap_score(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    overlap = len(left & right)
    return min(1.0, overlap / max(1, min(len(left), len(right), 3)))
