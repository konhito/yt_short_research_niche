"""Niche profile loader — reads YAML profiles and provides stage-specific context.

Each niche profile configures: script tone/hooks/CTAs, visual style/subjects,
voice pace/energy, caption styling, music mood, thumbnail strategy, and
topic discovery sources.
"""

import os
import yaml
from pathlib import Path
from typing import Any

from .log import log

# Niche profiles live in niches/ at the project root
NICHES_DIR = Path(__file__).resolve().parent.parent / "niches"

# Cache loaded profiles to avoid re-reading YAML on every stage
_cache: dict[str, dict] = {}


def load_niche(name: str = "general") -> dict:
    """Load a niche profile by name. Returns general fallback if not found."""
    name = (name or "general").strip().lower()

    if name in _cache:
        return _cache[name]

    profile_path = NICHES_DIR / f"{name}.yaml"
    if not profile_path.exists():
        log(f"Niche profile '{name}' not found at {profile_path}")
        if name != "general":
            log("Falling back to 'general' profile")
            return load_niche("general")
        # Return minimal default if even general.yaml is missing
        return _minimal_profile(name)

    try:
        with open(profile_path, "r", encoding="utf-8") as f:
            profile = yaml.safe_load(f) or {}
        profile.setdefault("name", name)
        _cache[name] = profile
        log(f"Loaded niche profile: {name}")
        return profile
    except Exception as e:
        log(f"Failed to parse niche profile '{name}': {e}")
        return _minimal_profile(name)


def _minimal_profile(name: str) -> dict:
    """Bare minimum profile when YAML is missing or broken."""
    return {
        "name": name,
        "display_name": name.title(),
        "script": {
            "tone": "clear, engaging, conversational",
            "pacing": "moderate, well structured",
            "word_count": "150 to 180",
        },
        "visuals": {
            "style": "cinematic, professional",
            "prompt_suffix": "photorealistic, cinematic lighting, high quality",
        },
        "voice": {},
        "captions": {},
        "music": {},
        "thumbnail": {},
        "discovery": {},
    }


def get_script_context(profile: dict) -> str:
    """Build the script intelligence block for the LLM prompt.

    Returns a multi-line string that goes into the Claude/Gemini/GPT prompt
    to shape the script tone, hooks, structure, and CTAs.
    """
    script = profile.get("script", {})
    if not script:
        return ""

    parts = []
    parts.append(f"NICHE: {profile.get('display_name', profile.get('name', 'General'))}")

    if script.get("tone"):
        parts.append(f"TONE: {script['tone']}")
    if script.get("pacing"):
        parts.append(f"PACING: {script['pacing']}")
    if script.get("perspective"):
        parts.append(f"PERSPECTIVE: {script['perspective']}")
    if script.get("word_count"):
        parts.append(f"TARGET WORD COUNT: {script['word_count']}")
    if script.get("sentence_style"):
        parts.append(f"SENTENCE STYLE: {script['sentence_style']}")

    # Hook patterns
    hooks = script.get("hooks", [])
    if hooks:
        hook_lines = []
        for h in hooks:
            template = h.get("template", "")
            when = h.get("when", "")
            if template:
                line = f"  {h.get('id', 'hook')}: \"{template}\""
                if when:
                    line += f" (use when: {when})"
                hook_lines.append(line)
        if hook_lines:
            parts.append("HOOK PATTERNS (pick the most appropriate for this topic):")
            parts.extend(hook_lines)

    # Structure guidance
    structure = script.get("structure", {})
    if structure:
        parts.append("SCRIPT STRUCTURE:")
        if structure.get("opening"):
            parts.append(f"  Opening: {structure['opening']}")
        if structure.get("middle"):
            parts.append(f"  Middle: {structure['middle']}")
        if structure.get("closing"):
            parts.append(f"  Closing: {structure['closing']}")

    # CTA variants
    ctas = script.get("cta_variants", [])
    if ctas:
        parts.append(f"CTA OPTIONS (pick one): {', '.join(ctas)}")

    # Forbidden phrases
    forbidden = script.get("forbidden_phrases", [])
    if forbidden:
        parts.append(f"NEVER USE: {', '.join(forbidden)}")

    return "\n".join(parts)


def get_visual_context(profile: dict) -> dict:
    """Extract visual intelligence for b-roll prompt shaping.

    Returns dict with style, mood, subjects, avoid, prompt_suffix.
    """
    return profile.get("visuals", {})


def get_visual_prompt_suffix(profile: dict) -> str:
    """Get the image prompt suffix from the niche profile."""
    visuals = profile.get("visuals", {})
    return visuals.get("prompt_suffix", "photorealistic, cinematic lighting, high quality")


def get_visual_subjects(profile: dict) -> dict:
    """Get preferred and avoided visual subjects."""
    visuals = profile.get("visuals", {})
    subjects = visuals.get("subjects", {})
    return {
        "prefer": subjects.get("prefer", []),
        "avoid": subjects.get("avoid", []),
    }


def get_voice_config(profile: dict, provider: str = "edge_tts", lang: str = "en") -> dict:
    """Get voice configuration for the specified provider and language."""
    provider = {"edge": "edge_tts"}.get((provider or "edge_tts").lower(), provider)
    voice = profile.get("voice", {})
    suggested = voice.get("suggested_voices", {})

    config = {
        "pace": voice.get("pace", ""),
        "energy": voice.get("energy", ""),
        "style": voice.get("style", ""),
    }

    provider_voices = suggested.get(provider, {})
    if isinstance(provider_voices, dict):
        config["voice_id"] = provider_voices.get(lang, provider_voices.get("en", ""))
        # Providers that ship a single voice_id + a settings dict (rather than
        # one voice_id per language) — ElevenLabs and 60db follow this shape.
        if provider in ("elevenlabs", "60db"):
            config["voice_id"] = provider_voices.get("voice_id", "")
            config["settings"] = provider_voices.get("settings", {})
    elif isinstance(provider_voices, str):
        config["voice_id"] = provider_voices

    return config


def get_caption_config(profile: dict) -> dict:
    """Get caption styling from the niche profile."""
    defaults = {
        "highlight_color": "#FFFF00",
        "text_color": "#FFFFFF",
        "font_family": "Arial",
        "font_size": 72,
        "font_weight": "bold",
        "position": "lower_third",
        "background": "semi_transparent_dark",
        "words_per_group": 4,
    }
    captions = profile.get("captions", {})
    defaults.update(captions)
    return defaults


def get_music_config(profile: dict) -> dict:
    """Get music mood and ducking config from the niche profile."""
    defaults = {
        "mood": "ambient, subtle, no lyrics",
        "energy": "medium",
        "tags": [],
        "duck_volume_speech": 0.12,
        "duck_volume_gap": 0.25,
    }
    music = profile.get("music", {})
    defaults.update(music)
    return defaults


def get_thumbnail_config(profile: dict) -> dict:
    """Get thumbnail style guidance from the niche profile."""
    return profile.get("thumbnail", {})


def get_editing_config(profile: dict) -> dict:
    """Return validated source counts, pacing, and effects for video editing."""
    defaults = {
        "style": "balanced",
        "cut_duration_seconds": [3, 6],
        "pexels_clips": [1, 3],
        "meme_beats": [0, 2],
        "ai_images": [2, 4],
        "youtube_clips": [0, 0],
        "reddit_clips": [0, 0],
        "research_images": [0, 3],
        "prefer_scraped_video": False,
        "minimum_video_candidates": 8,
        "harvest_workers": 4,
        "reddit_harvest_after": "30d",
        "effects": ["pan", "punch_zoom", "hard_cut"],
    }
    raw = {**defaults, **(profile.get("editing", {}) or {})}
    if "VIDEO_HARVEST_ENABLED" in os.environ:
        raw["prefer_scraped_video"] = os.environ["VIDEO_HARVEST_ENABLED"].lower() in {"1", "true", "yes", "on"}
    for env_name, key in (("YOUTUBE_HARVEST_DOWNLOADS", "youtube_clips"), ("REDDIT_HARVEST_DOWNLOADS", "reddit_clips")):
        if os.environ.get(env_name):
            limit = max(0, int(os.environ[env_name]))
            current = raw.get(key, [0, limit])
            raw[key] = [min(int(current[0]), limit), limit]
    if os.environ.get("MINIMUM_VIDEO_CANDIDATES"):
        raw["minimum_video_candidates"] = int(os.environ["MINIMUM_VIDEO_CANDIDATES"])
    if os.environ.get("REDDIT_HARVEST_AFTER"):
        raw["reddit_harvest_after"] = os.environ["REDDIT_HARVEST_AFTER"]
    allowed_styles = {"cinematic", "balanced", "meme_heavy"}
    allowed_effects = {"pan", "punch_zoom", "shake", "hard_cut", "zoom_in", "zoom_out"}

    def normalized_range(value, fallback):
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            return list(fallback)
        try:
            low, high = int(value[0]), int(value[1])
        except (TypeError, ValueError):
            return list(fallback)
        return [max(0, min(low, high)), max(0, max(low, high))]

    return {
        "style": raw["style"] if raw["style"] in allowed_styles else defaults["style"],
        "cut_duration_seconds": normalized_range(raw["cut_duration_seconds"], defaults["cut_duration_seconds"]),
        "pexels_clips": normalized_range(raw["pexels_clips"], defaults["pexels_clips"]),
        "meme_beats": normalized_range(raw["meme_beats"], defaults["meme_beats"]),
        "ai_images": normalized_range(raw["ai_images"], defaults["ai_images"]),
        "youtube_clips": normalized_range(raw["youtube_clips"], defaults["youtube_clips"]),
        "reddit_clips": normalized_range(raw["reddit_clips"], defaults["reddit_clips"]),
        "research_images": normalized_range(raw["research_images"], defaults["research_images"]),
        "prefer_scraped_video": bool(raw.get("prefer_scraped_video", False)),
        "minimum_video_candidates": max(0, int(raw.get("minimum_video_candidates", 8))),
        "harvest_workers": max(1, min(8, int(raw.get("harvest_workers", 4)))),
        "reddit_harvest_after": str(raw.get("reddit_harvest_after", "30d")),
        "effects": [effect for effect in raw.get("effects", []) if effect in allowed_effects] or defaults["effects"],
    }


def get_discovery_config(profile: dict) -> dict:
    """Get topic discovery sources from the niche profile."""
    discovery = profile.get("discovery", {}) or {}
    defaults = {
        "reddit": {"subreddits": []},
        "rss": {"feeds": []},
        "google_trends": {"category": "", "geo": "US"},
        "youtube_trending": {"category_id": ""},
    }
    return {
        section: {**values, **(discovery.get(section, {}) or {})}
        for section, values in defaults.items()
    }


def list_niches() -> list[str]:
    """List all available niche profile names."""
    if not NICHES_DIR.exists():
        return ["general"]
    names = [p.stem for p in NICHES_DIR.glob("*.yaml")]
    if "general" not in names:
        names.append("general")
    return sorted(names)
