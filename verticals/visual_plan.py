"""Validation and duration handling for mixed visual timelines."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path

from .broll import generate_broll
from .imgflip import create_meme, fetch_templates, select_template
from .log import log
from .mcp_assets import fetch_local_footage, fetch_pexels_footage, fetch_pixabay_footage


VALID_TYPES = {"pexels", "meme", "ai_image"}

def normalize_visual_plan(draft: dict, editing: dict) -> list[dict]:
    raw = draft.get("visual_plan")
    structured = isinstance(raw, list) and bool(raw)
    if not isinstance(raw, list) or not raw:
        raw = [
            {"type": "ai_image", "query": prompt, "effect": "pan"}
            for prompt in draft.get("broll_prompts", [])
        ]
    low, high = editing.get("cut_duration_seconds", [3, 6])
    effects = set(editing.get("effects", ["pan"]))
    limits = {
        "pexels": editing.get("pexels_clips", [0, 3])[1],
        "meme": editing.get("meme_beats", [0, 2])[1],
        "ai_image": editing.get("ai_images", [1, 4])[1],
    }
    counts = {kind: 0 for kind in VALID_TYPES}
    plan = []
    for item in raw:
        if not isinstance(item, dict) or item.get("type") not in VALID_TYPES:
            continue
        kind = item["type"]
        if counts[kind] >= limits[kind]:
            continue
        duration = float(item.get("duration_seconds", low))
        effect = item.get("effect", "pan")
        normalized = {
            **item,
            "query": str(item.get("query", "Cinematic supporting visual")),
            "duration_seconds": max(low, min(high, duration)),
            "effect": effect if effect in effects else next(iter(effects), "pan"),
        }
        counts[kind] += 1
        plan.append(normalized)
    if structured:
        base_query = str(draft.get("news") or next((item.get("query") for item in plan), "trending topic"))
        defaults = {
            "pexels": {"effect": "hard_cut"},
            "meme": {
                "effect": "punch_zoom",
                "template_hint": "surprised",
                "meme_text_top": "WHEN THE NEWS DROPS",
                "meme_text_bottom": "AND IT GETS WORSE",
            },
            "ai_image": {"effect": "pan"},
        }
        for kind, range_key in (("pexels", "pexels_clips"), ("meme", "meme_beats"), ("ai_image", "ai_images")):
            minimum = editing.get(range_key, [0, 0])[0]
            while counts[kind] < minimum:
                effect = defaults[kind]["effect"]
                if effect not in effects:
                    effect = next(iter(effects), "pan")
                plan.append({
                    "type": kind,
                    "query": base_query,
                    "duration_seconds": low,
                    **defaults[kind],
                    "effect": effect,
                })
                counts[kind] += 1
    return plan


def include_broll_prompt_assets(draft: dict, plan: list[dict], editing: dict) -> list[dict]:
    """Preserve original b-roll prompts as protected OpenAI image assets."""
    prompts = [str(prompt).strip() for prompt in draft.get("broll_prompts", []) if str(prompt).strip()]
    if not prompts:
        return plan
    low = editing.get("cut_duration_seconds", [3, 6])[0]
    effects = editing.get("effects", ["pan"])
    existing = {str(item.get("query", "")).strip().lower() for item in plan}
    protected = []
    for index, prompt in enumerate(prompts):
        if prompt.lower() in existing:
            continue
        protected.append({
            "type": "ai_image",
            "query": prompt,
            "duration_seconds": low,
            "effect": "pan" if "pan" in effects else effects[index % len(effects)] if effects else "pan",
            "protected": True,
            "asset_role": "broll_prompt",
        })
    return protected + plan


def apply_video_first_policy(plan: list[dict], editing: dict, harvested_count: int) -> list[dict]:
    """Use OpenAI images only when the harvested video pool is insufficient."""
    if not editing.get("prefer_scraped_video"):
        return plan
    minimum = int(editing.get("minimum_video_candidates", 8))
    max_ai = int(editing.get("ai_images", [0, 1])[1])
    if harvested_count >= minimum:
        max_ai = 0
    result = []
    ai_count = 0
    for item in plan:
        if item.get("type") == "ai_image":
            if ai_count >= max_ai:
                continue
            ai_count += 1
        result.append(item)
    return result


def enrich_pexels_search_queries(
    plan: list[dict], niche: str = "general", search_tags: list[str] | None = None
) -> list[dict]:
    """Assign shared AI discovery tags to stock-footage requests."""
    enriched = []
    pexels_index = 0
    for item in plan:
        updated = deepcopy(item)
        if updated.get("type") == "pexels":
            original_query = str(updated.get("query", ""))
            updated.setdefault("topic_query", original_query)
            updated["niche"] = niche
            tags = search_tags or []
            updated["search_query"] = tags[pexels_index % len(tags)] if tags else original_query
            pexels_index += 1
        enriched.append(updated)
    return enriched


def expand_visual_plan_for_duration(plan: list[dict], editing: dict, duration: float) -> list[dict]:
    """Add fresh visual requests so long voiceovers do not reuse a tiny pool."""
    if not plan or duration <= 0:
        return plan
    low, high = editing.get("cut_duration_seconds", [2, 5])
    average_cut = max(1.5, (float(low) + float(high)) / 2)
    target = max(len(plan), int((duration + average_cut - 0.01) // average_cut))
    target = min(target, int(editing.get("max_total_assets", 18)))
    expanded = deepcopy(plan)
    pattern = ["pexels", "meme", "ai_image", "meme"] if editing.get("style") == "meme_heavy" else ["pexels", "ai_image", "meme"]
    effects = editing.get("effects", ["pan"])
    base_queries = [str(item.get("query", "supporting visual")) for item in plan]
    suffixes = [
        "opening hook",
        "shocked reaction",
        "context visual",
        "escalation beat",
        "community reaction",
        "dramatic reveal",
        "proof moment",
        "final hot take",
    ]
    while len(expanded) < target:
        index = len(expanded)
        kind = pattern[(index - len(plan)) % len(pattern)]
        query = f"{base_queries[index % len(base_queries)]} {suffixes[index % len(suffixes)]}"
        item = {
            "type": kind,
            "query": query,
            "duration_seconds": low,
            "effect": effects[index % len(effects)] if effects else "pan",
        }
        if kind == "meme":
            item.update({
                "template_hint": "surprised reaction",
                "meme_text_top": "WAIT WHAT",
                "meme_text_bottom": "IT GETS WORSE",
            })
        expanded.append(item)
    return expanded


def normalize_timeline_duration(items: list[dict], duration: float) -> list[dict]:
    if not items or duration <= 0:
        return []
    segment = duration / len(items)
    result = []
    elapsed = 0.0
    for index, original in enumerate(items):
        item = deepcopy(original)
        end = duration if index == len(items) - 1 else elapsed + segment
        item["duration_seconds"] = end - elapsed
        result.append(item)
        elapsed = end
    return result


def resolve_visual_assets(plan: list[dict], work_dir: Path) -> list[dict]:
    """Resolve mixed provider items independently, falling back to OpenAI."""
    templates = fetch_templates() if any(item.get("type") == "meme" for item in plan) else None
    max_workers = min(6, max(1, len(plan)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        meme_offsets = _meme_offsets(plan)
        futures = [
            executor.submit(_resolve_visual_asset, index, item, work_dir, templates, meme_offsets.get(index, 0))
            for index, item in enumerate(plan)
        ]
        return [future.result() for future in futures]


def _resolve_visual_asset(index: int, item: dict, work_dir: Path, templates: list[dict] | None, meme_offset: int = 0) -> dict:
        item_dir = work_dir / f"visual_{index:02d}"
        item_dir.mkdir(parents=True, exist_ok=True)
        kind = item["type"]
        source = kind
        try:
            if kind == "meme":
                templates = templates if templates is not None else fetch_templates()
                template = select_template(
                    templates,
                    item.get("template_hint", ""),
                    f"{item.get('query', '')} {item.get('meme_text_top', '')} {item.get('meme_text_bottom', '')}",
                    offset=meme_offset,
                )
                path = create_meme(
                    str(template["id"]),
                    item.get("meme_text_top", ""),
                    item.get("meme_text_bottom", ""),
                    item_dir,
                )
                source = "imgflip"
                item = {**item, "meme_template_id": str(template["id"]), "meme_template_name": template.get("name", "")}
            elif kind == "pexels":
                search_query = item.get("search_query") or item["query"]
                local = fetch_local_footage(search_query, item_dir, niche=item.get("niche", "general"), limit=1)
                if local:
                    path = local[0]
                    source = "local_asset"
                else:
                    try:
                        seed = f"{work_dir.name}:{index}:{search_query}"
                        path = fetch_pexels_footage(
                            search_query, item_dir, limit=1, selection_seed=seed
                        )[0]
                        source = "pexels"
                    except Exception as pexels_exc:
                        log(f"Pexels footage failed for '{search_query}' ({pexels_exc}) - trying Pixabay")
                        path = fetch_pixabay_footage(
                            search_query, item_dir, limit=1, selection_seed=seed
                        )[0]
                        source = "pixabay"
            else:
                path = generate_broll([item["query"]], item_dir, provider="openai")[0]
                source = "openai"
        except Exception as exc:
            log(f"{kind} visual failed ({exc}) - falling back to portrait OpenAI image")
            path = generate_broll([item.get("query", "supporting visual")], item_dir, provider="openai")[0]
            source = "openai_fallback"
        return {**item, "path": str(path), "source": source}


def _meme_offsets(plan: list[dict]) -> dict[int, int]:
    offsets = {}
    seen = {}
    for index, item in enumerate(plan):
        if item.get("type") != "meme":
            continue
        key = f"{item.get('template_hint', '')}|{item.get('meme_text_top', '')}|{item.get('meme_text_bottom', '')}"
        offset = seen.get(key, 0)
        offsets[index] = offset
        seen[key] = offset + 1
    return offsets

