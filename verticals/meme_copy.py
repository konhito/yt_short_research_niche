"""Transcript-aware, non-repeating meme caption generation."""

from __future__ import annotations

import json
import re
from copy import deepcopy

from .llm import call_llm
from .log import log


GENERIC_COPY = {
    ("WAIT WHAT", "IT GETS WORSE"),
    ("WHEN THE NEWS DROPS", "AND IT GETS WORSE"),
}


def generate_meme_copy(
    plan: list[dict],
    script: str,
    transcript_words: list[dict],
    *,
    provider: str = "openai",
) -> list[dict]:
    result = deepcopy(plan)
    targets = [index for index, item in enumerate(result) if item.get("type") == "meme" and _is_generic(item)]
    if not targets:
        return result
    payload = {
        "script": script,
        "transcript_segments": _segments(transcript_words),
        "meme_beats": [
            {"index": index, "query": result[index].get("query", ""), "template_hint": result[index].get("template_hint", "")}
            for index in targets
        ],
        "rules": [
            "Return JSON only with a memes array.",
            "Write unique captions tied to each query and script beat.",
            "Never use WAIT WHAT, IT GETS WORSE, WHEN THE NEWS DROPS, or AND IT GETS WORSE.",
            "Keep top and bottom captions under 42 characters each.",
            "Do not repeat captions across memes.",
        ],
        "schema": {"memes": [{"index": targets[0], "top": "SHORT SETUP", "bottom": "SPECIFIC PUNCHLINE"}]},
    }
    try:
        raw = call_llm(
            "You write sharp meme captions for a short-form video.\n" + json.dumps(payload, ensure_ascii=False),
            provider=provider,
            max_tokens=1200,
        )
        parsed = _extract_json(raw)
        replacements = {int(item["index"]): item for item in parsed.get("memes", []) if isinstance(item, dict) and "index" in item}
    except Exception as exc:
        log(f"Meme caption writer failed ({exc}) - using transcript fallback")
        replacements = {}
    used = {
        (str(item.get("meme_text_top", "")).strip().upper(), str(item.get("meme_text_bottom", "")).strip().upper())
        for index, item in enumerate(result)
        if index not in targets
    }
    fallback_lines = _fallback_lines(script, result, targets)
    for position, index in enumerate(targets):
        replacement = replacements.get(index, {})
        top = _clean(replacement.get("top", ""))
        bottom = _clean(replacement.get("bottom", ""))
        pair = (top, bottom)
        if not top or not bottom or pair in used or pair in GENERIC_COPY:
            top, bottom = fallback_lines[position]
            pair = (top, bottom)
        while pair in used:
            bottom = _clean(f"{bottom} #{position + 1}")
            pair = (top, bottom)
        result[index]["meme_text_top"] = top
        result[index]["meme_text_bottom"] = bottom
        used.add(pair)
    return result


def _is_generic(item: dict) -> bool:
    pair = (
        str(item.get("meme_text_top", "")).strip().upper(),
        str(item.get("meme_text_bottom", "")).strip().upper(),
    )
    return pair in GENERIC_COPY or not all(pair)


def _segments(words: list[dict], size: int = 12) -> list[dict]:
    segments = []
    for index in range(0, len(words), size):
        group = words[index:index + size]
        if group:
            segments.append({
                "start": group[0].get("start", 0),
                "end": group[-1].get("end", 0),
                "text": " ".join(str(item.get("word", "")).strip() for item in group).strip(),
            })
    return segments[:30]


def _fallback_lines(script: str, plan: list[dict], targets: list[int]) -> list[tuple[str, str]]:
    sentences = [part.strip() for part in re.split(r"[.!?]+", script) if part.strip()]
    lines = []
    for position, index in enumerate(targets):
        query = str(plan[index].get("query", "REACTION")).strip()
        sentence = sentences[position % len(sentences)] if sentences else query
        top = _clean(query.upper() or f"STORY BEAT {position + 1}")
        words = sentence.upper().split()
        bottom = _clean(" ".join(words[-6:]) or f"BEAT {position + 1}")
        lines.append((top, bottom))
    return lines


def _clean(value: str) -> str:
    value = re.sub(r"\s+", " ", str(value)).strip().upper()
    return value[:42].rstrip()


def _extract_json(text: str) -> dict:
    cleaned = text.strip()
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, re.S)
    if match:
        cleaned = match.group(1)
    return json.loads(cleaned)
