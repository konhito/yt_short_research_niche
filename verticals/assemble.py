"""ffmpeg video assembly — frames + voiceover + music + captions."""

from pathlib import Path

from .broll import animate_frame, animate_meme_frame
from .config import MEDIA_DIR, run_cmd
from .log import log


def _ffmpeg_has_libass() -> bool:
    """Check whether this ffmpeg build ships the `ass` filter (libass).

    Some builds (e.g. minimal/static ones) omit libass; burning captions in
    would fail with `No such filter: 'ass'`, so we skip burn-in instead.
    """
    try:
        r = run_cmd(["ffmpeg", "-hide_banner", "-filters"], capture=True)
        return any(line.split()[1:2] == ["ass"] for line in r.stdout.splitlines())
    except Exception:
        return False


def get_audio_duration(path: Path) -> float:
    """Get duration of an audio file in seconds."""
    try:
        r = run_cmd(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture=True,
        )
        return float(r.stdout.strip())
    except Exception:
        import re

        r = run_cmd(
            ["ffmpeg", "-i", str(path)],
            capture=True,
            check=False,
        )
        m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", r.stderr or "")
        if not m:
            raise
        hours, mins, secs = m.groups()
        return int(hours) * 3600 + int(mins) * 60 + float(secs)


def assemble_video(
    frames: list[Path],
    voiceover: Path,
    out_dir: Path,
    job_id: str,
    lang: str = "en",
    ass_path: str | None = None,
    music_path: str | None = None,
    duck_filter: str | None = None,
    timeline: list[dict] | None = None,
) -> Path:
    """Assemble final video from frames, voiceover, captions, and music."""
    log("Assembling video...")
    duration = get_audio_duration(voiceover)
    if timeline:
        frames = [Path(item["path"]) for item in timeline]
    if not frames:
        raise ValueError("No visual assets available for assembly")
    per_frame = duration / len(frames)
    effects = ["zoom_in", "pan_right", "zoom_out"]
    video_suffixes = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}

    # Animate each frame with Ken Burns effect
    animated = []
    for i, frame in enumerate(frames):
        anim = out_dir / f"anim_{i}.mp4"
        segment_duration = timeline[i]["duration_seconds"] if timeline else per_frame + 0.1
        effect = timeline[i].get("effect", effects[i % len(effects)]) if timeline else effects[i % len(effects)]
        fit = timeline[i].get("fit", "") if timeline else ""
        source = timeline[i].get("source", "") if timeline else ""
        kind = timeline[i].get("type", "") if timeline else ""
        if frame.suffix.lower() in video_suffixes:
            source_start = float(timeline[i].get("source_start_seconds", 0.0)) if timeline else 0.0
            _fit_clip(frame, anim, segment_duration, source_start=source_start)
        elif fit in {"fit_width_pad", "contain_pad"} or source == "imgflip" or kind == "meme":
            fill_color = timeline[i].get("fill_color", "#0D0D0D") if timeline else "#0D0D0D"
            animate_meme_frame(frame, anim, segment_duration, effect, fill_color)
        else:
            animate_frame(frame, anim, segment_duration, effect)
        animated.append(anim)

    # Concat animated segments (escape single quotes for ffmpeg concat demuxer)
    concat_file = out_dir / "concat.txt"
    def _esc(p):
        return str(p).replace("'", "'\\''" )
    concat_lines = []
    for index, path in enumerate(animated):
        concat_lines.append(f"file '{_esc(path)}'")
        if timeline:
            concat_lines.append(f"duration {float(timeline[index]['duration_seconds']):.3f}")
    if animated:
        # ffmpeg's concat demuxer applies the final duration only when the last
        # file is repeated. Without this, some MP4 timebases can collapse output.
        concat_lines.append(f"file '{_esc(animated[-1])}'")
    concat_file.write_text("\n".join(concat_lines), encoding="utf-8")

    merged_video = out_dir / "merged_video.mp4"
    concat_cmd = ["ffmpeg"]
    for path in animated:
        concat_cmd.extend(["-i", str(path)])
    reset_filters = [
        f"[{index}:v]scale=1080:1920,setsar=1,setpts=PTS-STARTPTS[v{index}]"
        for index in range(len(animated))
    ]
    concat_inputs = "".join(f"[v{index}]" for index in range(len(animated)))
    concat_filter = ";".join(reset_filters + [
        f"{concat_inputs}concat=n={len(animated)}:v=1:a=0[vout]"
    ])
    concat_cmd.extend([
        "-filter_complex", concat_filter,
        "-map", "[vout]",
        "-r", "30",
        "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
        str(merged_video), "-y", "-loglevel", "quiet",
    ])
    run_cmd(concat_cmd)

    # Build the final ffmpeg command with optional captions + music
    out_path = MEDIA_DIR / f"verticals_{job_id}_{lang}.mp4"

    # Determine video filter (captions via ASS)
    vf_parts = []
    if ass_path and Path(ass_path).exists():
        if _ffmpeg_has_libass():
            # Escape special chars in path for ffmpeg filter
            escaped_ass = _escape_ffmpeg_filter_path(Path(ass_path))
            vf_parts.append(f"ass={escaped_ass}")
        else:
            log(
                "WARNING: this ffmpeg build has no libass — captions will NOT "
                "be burned in. The SRT is still uploaded to YouTube. Install "
                "an ffmpeg with libass (brew/apt builds include it) for "
                "burned-in captions."
            )
    vf = ",".join(vf_parts) if vf_parts else None

    if music_path and Path(music_path).exists():
        # Three inputs: video, voiceover, music
        cmd = ["ffmpeg", "-i", str(merged_video), "-i", str(voiceover)]

        # Loop music to match video duration, apply ducking
        music_filter = f"[2:a]aloop=loop=-1:size=2e+09,atrim=0:{duration}"
        if duck_filter:
            music_filter += f",{duck_filter}"
        music_filter += "[music]"

        # Mix voiceover + ducked music
        audio_filter = f"{music_filter};[1:a][music]amix=inputs=2:duration=first:dropout_transition=2[aout]"

        cmd += [
            "-stream_loop", "-1", "-i", str(music_path),
            "-filter_complex", audio_filter,
        ]

        if vf:
            cmd += ["-vf", vf]

        cmd += [
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "fast", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path), "-y", "-loglevel", "quiet",
        ]
    else:
        # Two inputs: video + voiceover (no music)
        cmd = ["ffmpeg", "-i", str(merged_video), "-i", str(voiceover)]

        if vf:
            cmd += ["-vf", vf]

        cmd += [
            "-c:v", "libx264" if vf else "copy",
            "-c:a", "aac", "-shortest",
            str(out_path), "-y", "-loglevel", "quiet",
        ]

    try:
        run_cmd(cmd)
    except Exception as exc:
        if vf and ass_path and "ass=" in vf:
            log(
                "WARNING: ffmpeg caption burn-in failed; retrying without ASS "
                f"filter. Error: {exc}"
            )
            retry_cmd = [part for part in cmd if part not in ("-vf", vf)]
            run_cmd(retry_cmd)
        else:
            raise
    log(f"Video assembled: {out_path}")
    return out_path


def _fit_clip(src: Path, out_path: Path, duration: float, source_start: float = 0.0):
    """Trim/loop a video clip and crop it to 9:16 portrait."""
    run_cmd([
        "ffmpeg",
        "-stream_loop", "-1",
        "-ss", str(max(0.0, source_start)),
        "-i", str(src),
        "-t", str(duration),
        "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
        "-an",
        "-c:v", "libx264",
        "-preset", "fast",
        "-pix_fmt", "yuv420p",
        str(out_path),
        "-y",
        "-loglevel", "quiet",
    ])


def _escape_ffmpeg_filter_path(path: Path) -> str:
    """Escape a filesystem path for ffmpeg filter arguments on Windows."""
    return path.as_posix().replace(":", "\\:").replace("'", "\\'")
