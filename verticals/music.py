"""Background music - AI plan + track selection + volume ducking."""

import random
import re
from pathlib import Path

from .config import run_cmd
from .log import log

# Music directory ships with the package
MUSIC_DIR = Path(__file__).resolve().parent.parent / "music"


def _find_tracks() -> list[Path]:
    """Find all MP3 tracks in the music/ directory."""
    if not MUSIC_DIR.exists():
        return []
    return sorted(MUSIC_DIR.glob("*.mp3"))


def _rank_tracks(tracks: list[Path], tags: list[str]) -> list[Path]:
    """Return tracks tied for the strongest exact filename-tag match."""
    normalized_tags = {str(tag).strip().lower() for tag in tags if str(tag).strip()}
    scored = []
    for track in tracks:
        tokens = set(re.findall(r"[a-z0-9]+", track.stem.lower()))
        scored.append((len(tokens & normalized_tags), track))
    best = max((score for score, _ in scored), default=0)
    return [track for score, track in scored if score == best] if best else tracks


def _build_music_plan(profile: dict, draft: dict | None = None) -> dict:
    """Build a lightweight music plan from niche + draft context."""
    draft = draft or {}
    existing = draft.get("music_plan")
    if isinstance(existing, dict) and existing:
        return existing

    music = profile.get("music", {})
    tags = music.get("tags", []) or []
    return {
        "mood": music.get("mood", "ambient, subtle, no lyrics"),
        "energy": music.get("energy", "medium"),
        "tags": tags[:5],
        "ducking_notes": "Keep vocals clear and music low under speech.",
    }


def _get_speech_regions(audio_path: Path) -> list[tuple[float, float]]:
    """Extract speech regions from Whisper word timestamps."""
    try:
        from .captions import _whisper_word_timestamps

        words = _whisper_word_timestamps(audio_path)
        if words:
            regions = []
            region_start = words[0]["start"]
            region_end = words[0]["end"]

            for w in words[1:]:
                if w["start"] - region_end < 0.5:
                    region_end = w["end"]
                else:
                    regions.append((region_start, region_end))
                    region_start = w["start"]
                    region_end = w["end"]
            regions.append((region_start, region_end))
            return regions
    except Exception:
        pass

    try:
        from .assemble import get_audio_duration

        dur = get_audio_duration(audio_path)
        return [(0.0, dur)]
    except Exception:
        return [(0.0, 60.0)]


def build_duck_filter(
    speech_regions: list[tuple[float, float]],
    buffer: float = 0.3,
    vol_speech: float = 0.12,
    vol_gap: float = 0.25,
) -> str:
    """Build ffmpeg volume filter expression for ducking during speech."""
    if not speech_regions:
        return f"volume={vol_gap}"

    conditions = []
    for start, end in speech_regions:
        s = max(0, start - buffer)
        e = end + buffer
        conditions.append(f"between(t,{s:.2f},{e:.2f})")

    condition_expr = "+".join(conditions)
    return f"volume='if({condition_expr}, {vol_speech}, {vol_gap})':eval=frame"


def _get_audio_duration(path: Path) -> float:
    from .assemble import get_audio_duration

    return get_audio_duration(path)


def generate_procedural_music(plan: dict, duration: float, out_path: Path) -> Path:
    """Generate a lyric-free synth bed when no licensed track is installed."""
    energy = str(plan.get("energy", "medium")).lower()
    pulse = 6 if energy == "high" else 4 if energy == "medium" else 2
    bass = 110 if energy == "high" else 82
    lead = bass * 2
    fade_out = max(0.0, duration - 2.0)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    filter_complex = (
        f"[0:a]volume=0.16,tremolo=f={pulse}:d=0.55[a0];"
        f"[1:a]volume=0.07,tremolo=f={max(1, pulse // 2)}:d=0.35[a1];"
        f"[a0][a1]amix=inputs=2:duration=longest,lowpass=f=1800,"
        f"afade=t=in:st=0:d=1.5,afade=t=out:st={fade_out}:d=2[aout]"
    )
    run_cmd([
        "ffmpeg",
        "-f", "lavfi", "-i", f"sine=frequency={bass}:duration={duration}",
        "-f", "lavfi", "-i", f"sine=frequency={lead}:duration={duration}",
        "-filter_complex", filter_complex,
        "-map", "[aout]", "-q:a", "4", str(out_path), "-y", "-loglevel", "quiet",
    ])
    log(f"Generated procedural background music: {out_path.name}")
    return out_path


def select_and_prepare_music(
    voiceover_path: Path,
    work_dir: Path,
    duck_speech: float = 0.12,
    duck_gap: float = 0.25,
    profile: dict | None = None,
    draft: dict | None = None,
) -> dict:
    """Select a track, build duck filter, and return the music plan."""
    profile = profile or {}
    plan = _build_music_plan(profile, draft=draft)
    log(
        "Music plan: "
        f"mood={plan.get('mood', '')}, "
        f"energy={plan.get('energy', '')}, "
        f"tags={', '.join(plan.get('tags', [])[:5])}"
    )

    tracks = _find_tracks()
    if not tracks:
        try:
            duration = _get_audio_duration(voiceover_path)
            track = generate_procedural_music(plan, duration, work_dir / "generated_music.mp3")
            speech_regions = _get_speech_regions(voiceover_path)
            duck_filter = build_duck_filter(speech_regions, vol_speech=duck_speech, vol_gap=duck_gap)
            return {"track_path": str(track), "duck_filter": duck_filter, "plan": plan}
        except Exception as exc:
            log(f"Background music generation failed ({exc}) - continuing without music")
            return {"plan": plan}

    candidates = _rank_tracks(tracks, plan.get("tags", []))
    track = random.choice(candidates)
    log(f"Selected music track: {track.name}")

    speech_regions = _get_speech_regions(voiceover_path)
    duck_filter = build_duck_filter(speech_regions, vol_speech=duck_speech, vol_gap=duck_gap)
    log(f"Built duck filter with {len(speech_regions)} speech regions")

    return {
        "track_path": str(track),
        "duck_filter": duck_filter,
        "plan": plan,
    }
