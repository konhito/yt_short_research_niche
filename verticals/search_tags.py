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


def build_search_tags_for_beat(beat: dict, niche: str = "general") -> list[str]:
    """Build five beat-specific search phrases from beat metadata."""
    script_text = re.sub(r"\s+", " ", str(beat.get("script_text", "")).strip())
    entities = [
        re.sub(r"\s+", " ", str(item)).strip()
        for item in beat.get("entities", [])
        if str(item).strip()
    ]
    intent = re.sub(r"\s+", " ", str(beat.get("intent", niche)).strip())
    avoid_terms = {
        re.sub(r"\s+", " ", str(item)).strip().lower()
        for item in beat.get("avoid", [])
        if str(item).strip()
    }

    candidates = [
        f"{script_text} {niche}".strip(),
        " ".join(entities[:3]).strip(),
        f"{intent} {entities[0] if entities else niche}".strip(),
        f"{niche} {entities[1] if len(entities) > 1 else intent}".strip(),
        script_text[:64] or niche,
    ]
    tags = []
    for candidate in candidates:
        cleaned = re.sub(r"\s+", " ", candidate).strip(" ,.-")
        lowered = cleaned.lower()
        if len(cleaned.split()) < 2 or lowered in {item.lower() for item in tags}:
            continue
        if any(avoid in lowered for avoid in avoid_terms):
            continue
        tags.append(cleaned[:140])
    while len(tags) < TAG_COUNT:
        fallback = f"{niche} {FALLBACK_INTENTS[len(tags) % len(FALLBACK_INTENTS)]}".strip()
        if fallback.lower() not in {item.lower() for item in tags}:
            tags.append(fallback)
    return tags[:TAG_COUNT]


def normalize_search_tags(draft: dict) -> list[str]:
    """Return exactly five unique, topic-anchored search phrases."""
    raw = draft.get("search_tags", [])
    if not isinstance(raw, list):
        raw = []
    tags = _unique_clean(raw)
    if not tags and isinstance(draft.get("script_beats"), list):
        for beat in draft["script_beats"]:
            if not isinstance(beat, dict):
                continue
            tags.extend(build_search_tags_for_beat(beat, niche=str(draft.get("niche", "general"))))
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
