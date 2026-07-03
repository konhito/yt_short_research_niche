"""Shared AI-generated discovery tags for every external asset provider."""

from __future__ import annotations

import re


TAG_COUNT = 5
FALLBACK_INTENTS = (
    "latest footage",
    "official reaction",
    "visual comparison",
    "explained evidence",
    "community discussion",
)


def normalize_search_tags(draft: dict) -> list[str]:
    """Return exactly five unique, topic-anchored search phrases."""
    raw = draft.get("search_tags", [])
    if not isinstance(raw, list):
        raw = []
    tags = _unique_clean(raw)
    topic = _topic(draft)
    for intent in FALLBACK_INTENTS:
        if len(tags) >= TAG_COUNT:
            break
        candidate = f"{topic} {intent}".strip()
        if candidate.lower() not in {item.lower() for item in tags}:
            tags.append(candidate)
    return tags[:TAG_COUNT]


def _topic(draft: dict) -> str:
    value = draft.get("news") or draft.get("youtube_title") or draft.get("script") or "current story"
    return re.sub(r"\s+", " ", str(value)).strip()[:120]


def _unique_clean(values: list) -> list[str]:
    result = []
    seen = set()
    for value in values:
        cleaned = re.sub(r"\s+", " ", str(value)).strip(" ,.-")
        key = cleaned.lower()
        if len(cleaned.split()) < 3 or key in seen:
            continue
        seen.add(key)
        result.append(cleaned[:140])
    return result
