"""CLI entry point — python -m verticals."""

import argparse
import sys
import time
from pathlib import Path

from .config import CONFIG_FILE, DRAFTS_DIR, MEDIA_DIR, run_setup
from .log import log, set_verbose
from .niche import list_niches


def maybe_run_setup(args):
    """Run first-run setup only for commands that need creator credentials.

    Help, niche listing, topic discovery, and local/free-provider paths should
    not block on an interactive setup wizard.
    """
    if CONFIG_FILE.exists() or args.cmd not in {"draft", "run"}:
        return

    provider = getattr(args, "provider", None)
    if provider in {"ollama", "gemini", "openai"}:
        return

    print("  First run detected. Running setup...")
    run_setup()


def cmd_draft(args):
    from .draft import generate_draft
    from .state import PipelineState
    import json

    DRAFTS_DIR.mkdir(parents=True, exist_ok=True)
    job_id = str(int(time.time()))

    niche = getattr(args, "niche", "general") or "general"
    platform = getattr(args, "platform", "shorts") or "shorts"
    provider = getattr(args, "provider", None)

    print(f"\n  Drafting: {args.news} [niche: {niche}, platform: {platform}]\n")
    draft = generate_draft(
        args.news,
        getattr(args, "context", ""),
        niche=niche,
        platform=platform,
        provider=provider,
    )
    draft["job_id"] = job_id

    out_path = DRAFTS_DIR / f"{job_id}.json"
    state = PipelineState(draft)
    state.complete_stage("research")
    state.complete_stage("draft")
    state.save(out_path)

    print(f"\n  Draft saved: {out_path}")
    print(f"\n  Script:\n{draft['script']}")
    print(f"\n  Title: {draft.get('youtube_title', '')}")
    print(f"\n  B-roll prompts:")
    for i, p in enumerate(draft.get("broll_prompts", [])):
        print(f"  {i+1}. {p}")

    return out_path


def cmd_produce(args):
    from .broll import generate_broll
    from .tts import generate_voiceover
    from .captions import generate_captions
    from .music import select_and_prepare_music
    from .assemble import assemble_video, get_audio_duration
    from .mcp_assets import fetch_pexels_footage
    from .niche import load_niche, get_discovery_config, get_editing_config, get_voice_config, get_caption_config, get_music_config
    from .visual_plan import (
        apply_video_first_policy,
        enrich_pexels_search_queries,
        expand_visual_plan_for_duration,
        include_broll_prompt_assets,
        normalize_visual_plan,
        resolve_visual_assets,
    )
    from .editor_plan import create_editor_timeline
    from .meme_copy import generate_meme_copy
    from .research_assets import discover_and_download_research_images
    from .video_harvest import harvest_video_sources
    from .state import PipelineState
    from concurrent.futures import ThreadPoolExecutor
    import json
    import shutil

    draft_path = Path(args.draft)
    draft = json.loads(draft_path.read_text())
    job_id = draft["job_id"]
    lang = args.lang
    state = PipelineState(draft)

    # Load niche profile for voice/caption/music config
    niche_name = draft.get("niche", "general")
    profile = load_niche(niche_name)
    editing_config = get_editing_config(profile)

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    work_dir = MEDIA_DIR / f"work_{job_id}_{lang}"
    work_dir.mkdir(exist_ok=True)

    force = getattr(args, "force", False)
    tts_provider = getattr(args, "voice", None)
    footage_provider = getattr(args, "footage_provider", None)
    script = getattr(args, "script", None) or (
        draft.get("script_hi") if lang == "hi" else draft.get("script")
    )

    print(f"\n  Producing {lang.upper()} video for job {job_id} [niche: {niche_name}]")

    # Voiceover (niche-aware voice selection)
    if force or not state.is_done("voiceover"):
        voice_config = get_voice_config(
            profile,
            provider=tts_provider or "edge_tts",
            lang=lang,
        )
        vo_path = generate_voiceover(
            script, work_dir, lang,
            provider=tts_provider,
            voice_config=voice_config,
        )
        state.complete_stage("voiceover", {"path": str(vo_path)})
    else:
        log("Skipping voiceover (already done)")
        vo_path = Path(state.get_artifact("voiceover", "path"))

    # Whisper + Captions (niche-aware styling)
    caption_config = get_caption_config(profile)
    if force or not state.is_done("captions"):
        captions_result = generate_captions(
            vo_path, work_dir, lang,
            highlight_color=caption_config.get("highlight_color", "#FFFF00"),
            text_color=caption_config.get("text_color", "#FFFFFF"),
            words_per_group=caption_config.get("words_per_group", 4),
            font_family=caption_config.get("font_family", "Arial"),
            font_size=int(caption_config.get("font_size", 72)),
            font_weight=caption_config.get("font_weight", "bold"),
            position=caption_config.get("position", "lower_third"),
            background=caption_config.get("background", "semi_transparent_dark"),
        )
        state.complete_stage("captions", {
            "srt_path": str(captions_result.get("srt_path", "")),
            "ass_path": str(captions_result.get("ass_path", "")),
            "words": captions_result.get("words", []),
        })
    else:
        log("Skipping captions (already done)")
        captions_result = {
            "srt_path": state.get_artifact("captions", "srt_path", ""),
            "ass_path": state.get_artifact("captions", "ass_path", ""),
            "words": state.get_artifact("captions", "words", []),
        }

    # Music (niche-aware mood/ducking)
    music_config = get_music_config(profile)
    if force or not state.is_done("music"):
        music_result = select_and_prepare_music(
            vo_path, work_dir,
            duck_speech=music_config.get("duck_volume_speech", 0.12),
            duck_gap=music_config.get("duck_volume_gap", 0.25),
            profile=profile,
            draft=draft,
        )
        state.complete_stage("music", {
            "track_path": str(music_result.get("track_path", "")),
            "duck_filter": music_result.get("duck_filter", ""),
            "plan": music_result.get("plan", {}),
        })
    else:
        log("Skipping music (already done)")
        music_result = {
            "track_path": state.get_artifact("music", "track_path", ""),
            "duck_filter": state.get_artifact("music", "duck_filter", ""),
            "plan": state.get_artifact("music", "plan", {}),
        }

    duration = get_audio_duration(vo_path)

    # B-roll / footage. This happens after voiceover so the asset pool can
    # grow to the actual narration length instead of looping a tiny set.
    if force or not state.is_done("broll"):
        prompts = draft.get("broll_prompts", ["Cinematic landscape"] * 3)
        visual_plan = normalize_visual_plan(draft, editing_config)
        if visual_plan and draft.get("visual_plan"):
            visual_plan = include_broll_prompt_assets(draft, visual_plan, editing_config)
            visual_plan = expand_visual_plan_for_duration(visual_plan, editing_config, duration)
            visual_plan = enrich_pexels_search_queries(
                visual_plan,
                niche=niche_name,
                search_tags=draft.get("search_tags", []),
            )
            visual_plan = generate_meme_copy(
                visual_plan,
                script,
                captions_result.get("words", []),
                provider="openai",
            )
            non_ai_plan = [item for item in visual_plan if item.get("type") != "ai_image"]
            ai_plan = [item for item in visual_plan if item.get("type") == "ai_image"]
            discovery = get_discovery_config(profile)
            subreddits = discovery.get("reddit", {}).get("subreddits", [])
            if editing_config.get("prefer_scraped_video"):
                with ThreadPoolExecutor(max_workers=3) as executor:
                    harvest_future = executor.submit(
                        harvest_video_sources,
                        draft,
                        work_dir,
                        niche=niche_name,
                        editing=editing_config,
                        subreddits=subreddits,
                    )
                    visual_future = executor.submit(resolve_visual_assets, non_ai_plan, work_dir)
                    research_image_future = executor.submit(
                        discover_and_download_research_images,
                        draft.get("search_tags", []),
                        draft.get("research_images", []),
                        work_dir / "research_images",
                        int(editing_config.get("research_images", [1, 4])[1]),
                        niche_name,
                    )
                    harvest_result = harvest_future.result()
                    resolved_visuals = visual_future.result()
                    research_assets = research_image_future.result()
            else:
                harvest_result = {"assets": [], "rejected": [], "manifests": {}}
                resolved_visuals = resolve_visual_assets(non_ai_plan, work_dir)
                research_assets = discover_and_download_research_images(
                    draft.get("search_tags", []),
                    draft.get("research_images", []),
                    work_dir / "research_images",
                    int(editing_config.get("research_images", [1, 4])[1]),
                    niche_name,
                )
            ai_plan = apply_video_first_policy(ai_plan, editing_config, len(harvest_result.get("assets", [])))
            resolved_ai = resolve_visual_assets(ai_plan, work_dir / "ai_fallback") if ai_plan else []
            asset_timeline = harvest_result.get("assets", []) + research_assets + resolved_visuals + resolved_ai
            frames = [Path(item["path"]) for item in asset_timeline]
            counts = {}
            for item in asset_timeline:
                counts[item["source"]] = counts.get(item["source"], 0) + 1
            state.complete_stage("broll", {
                "assets": [str(f) for f in frames],
                "timeline": asset_timeline,
                "provider_counts": counts,
                "target_duration": duration,
                "harvest_manifests": harvest_result.get("manifests", {}),
                "harvest_rejected": len(harvest_result.get("rejected", [])),
            })
        elif footage_provider == "pexels":
            asset_timeline = None
            visual_assets = []
            for prompt in prompts[:3]:
                try:
                    visual_assets.extend(fetch_pexels_footage(prompt, work_dir, limit=1))
                except Exception as exc:
                    log(f"Pexels footage failed for prompt '{prompt}': {exc} - falling back")
            if visual_assets:
                frames = visual_assets
                state.complete_stage(
                    "broll",
                    {"assets": [str(f) for f in visual_assets], "provider": "pexels"},
                )
            else:
                frames = generate_broll(prompts, work_dir, provider="openai")
                state.complete_stage("broll", {"frames": [str(f) for f in frames]})
        else:
            asset_timeline = None
            frames = generate_broll(prompts, work_dir, provider="openai")
            state.complete_stage("broll", {"frames": [str(f) for f in frames]})
    else:
        log("Skipping b-roll (already done)")
        assets = state.get_artifact("broll", "assets", [])
        if assets:
            frames = [Path(f) for f in assets]
        else:
            frames = [Path(f) for f in state.get_artifact("broll", "frames", [])]
        asset_timeline = state.get_artifact("broll", "timeline", None)

    # Editor brain: choose the cut order/effects from the full asset pool.
    if force or not state.is_done("editor"):
        if asset_timeline:
            timeline = create_editor_timeline(
                draft=draft,
                transcript_words=captions_result.get("words", []),
                assets=asset_timeline,
                music_plan=music_result.get("plan", {}),
                duration=duration,
                editing=editing_config,
                provider="openai",
            )
            frames = [Path(item["path"]) for item in timeline]
            from .asset_history import mark_used_assets
            mark_used_assets(timeline, str(job_id))
            state.complete_stage("editor", {"timeline": timeline})
        else:
            timeline = None
            state.complete_stage("editor", {"timeline": []})
    else:
        log("Skipping editor brain (already done)")
        timeline = state.get_artifact("editor", "timeline", None)
        if timeline:
            frames = [Path(item["path"]) for item in timeline]

    # Assemble
    if force or not state.is_done("assemble"):
        video_path = assemble_video(
            frames=frames,
            voiceover=vo_path,
            out_dir=work_dir,
            job_id=job_id,
            lang=lang,
            ass_path=captions_result.get("ass_path"),
            music_path=music_result.get("track_path"),
            duck_filter=music_result.get("duck_filter"),
            timeline=timeline,
        )
        state.complete_stage("assemble", {"video_path": str(video_path)})
    else:
        log("Skipping assembly (already done)")
        video_path = Path(state.get_artifact("assemble", "video_path"))

    # Save SRT to media dir
    srt_path = captions_result.get("srt_path")
    if srt_path and Path(srt_path).exists():
        final_srt = MEDIA_DIR / f"verticals_{job_id}_{lang}.srt"
        shutil.copy(srt_path, final_srt)
        draft[f"srt_{lang}"] = str(final_srt)

    draft[f"video_{lang}"] = str(video_path)
    if music_result.get("plan"):
        draft["music_plan"] = music_result["plan"]
    state.save(draft_path)

    print(f"\n  Video: {video_path}")
    return video_path


def cmd_upload(args):
    from .upload import upload_to_youtube
    from .thumbnail import generate_thumbnail
    from .state import PipelineState
    from .niche import get_thumbnail_config, load_niche
    import json

    draft_path = Path(args.draft)
    draft = json.loads(draft_path.read_text())
    lang = args.lang
    state = PipelineState(draft)
    force = getattr(args, "force", False)
    thumbnail_provider = getattr(args, "thumbnail_provider", "openai")
    meme_template_id = getattr(args, "meme_template_id", None)
    thumbnail_config = get_thumbnail_config(load_niche(draft.get("niche", "general")))

    video_path = Path(draft.get(f"video_{lang}", ""))
    srt_path_str = draft.get(f"srt_{lang}")
    srt_path = Path(srt_path_str) if srt_path_str else None

    if not video_path.exists():
        print(f"  No produced video found for lang={lang}. Run produce first.")
        sys.exit(1)

    # Thumbnail
    thumb_path = None
    if force or not state.is_done("thumbnail"):
        try:
            thumb_path = generate_thumbnail(
                draft,
                MEDIA_DIR,
                provider=thumbnail_provider,
                meme_template_id=meme_template_id,
                profile_config=thumbnail_config,
            )
            state.complete_stage("thumbnail", {"path": str(thumb_path)})
        except Exception as e:
            log(f"Thumbnail generation failed: {e} - uploading without thumbnail")
    else:
        thumb_p = state.get_artifact("thumbnail", "path", "")
        if thumb_p and Path(thumb_p).exists():
            thumb_path = Path(thumb_p)

    # Upload
    if force or not state.is_done("upload"):
        url = upload_to_youtube(video_path, draft, srt_path, lang, thumb_path)
        state.complete_stage("upload", {"url": url})
    else:
        url = state.get_artifact("upload", "url", "")
        log(f"Skipping upload (already done): {url}")

    draft[f"youtube_url_{lang}"] = url
    state.save(draft_path)
    print(f"\n  Live: {url}")
    return url


def cmd_run(args):
    draft_path = cmd_draft(args)
    if args.dry_run:
        print("  Dry run — skipping produce + upload")
        return

    class ProduceArgs:
        draft = str(draft_path)
        lang = args.lang
        script = None
        force = False
        voice = getattr(args, "voice", None)

    video_path = cmd_produce(ProduceArgs())

    class UploadArgs:
        draft = str(draft_path)
        lang = args.lang
        force = False

    try:
        url = cmd_upload(UploadArgs())
        print(f"\n  Done! {url}")
    except FileNotFoundError as exc:
        # Keep the produced video when YouTube OAuth is not configured yet.
        print(f"\n  Upload skipped: {exc}")
        print(f"\n  Done! Video ready: {video_path}")
        return video_path


def cmd_topics(args):
    from .topics import TopicEngine

    niche = getattr(args, "niche", "general") or "general"
    engine = TopicEngine(niche=niche)
    candidates = engine.discover(limit=getattr(args, "limit", 15))

    if not candidates:
        print("  No topics found from enabled sources.")
        return

    print(f"\n  Trending topics for [{niche}] ({len(candidates)} found):\n")
    for i, topic in enumerate(candidates, 1):
        score = f" [{topic.trending_score:.2f}]" if topic.trending_score else ""
        print(f"  {i:2d}. [{topic.source}] {topic.title}{score}")
        if topic.summary:
            print(f"      {topic.summary[:100]}")


def cmd_harvest(args):
    """Harvest licensed YouTube and Reddit candidates for an existing draft."""
    from .video_harvest import harvest_video_sources
    from .niche import get_discovery_config, get_editing_config, load_niche
    import json

    draft_path = Path(args.draft)
    draft = json.loads(draft_path.read_text(encoding="utf-8"))
    niche = getattr(args, "niche", None) or draft.get("niche", "general")
    profile = load_niche(niche)
    editing = get_editing_config(profile)
    editing["youtube_clips"] = [0, args.downloads]
    editing["reddit_clips"] = [0, args.downloads]
    editing["yt_harvest_results"] = args.results
    editing["reddit_harvest_results"] = args.results
    out_dir = MEDIA_DIR / f"harvest_{draft.get('job_id', int(time.time()))}"
    result = harvest_video_sources(
        draft,
        out_dir,
        niche=niche,
        editing=editing,
        subreddits=get_discovery_config(profile).get("reddit", {}).get("subreddits", []),
    )
    print(f"\n  Harvested {len(result.get('assets', []))} clip(s)")
    print(f"  Rejected {len(result.get('rejected', []))} candidate(s)")
    print(f"  Manifests: {result.get('manifests', {})}")
    return result


def cmd_niches(args):
    """List all available niche profiles."""
    niches = list_niches()
    print(f"\n  Available niches ({len(niches)}):\n")
    for n in niches:
        from .niche import load_niche
        profile = load_niche(n)
        display = profile.get("display_name", n)
        desc = profile.get("description", "")[:80]
        print(f"    {n:20s}  {display}")
        if desc:
            print(f"    {' ':20s}  {desc}")


def cmd_voices(args):
    """List voices available for a TTS provider.

    Currently only 60db is supported — it exposes GET /myvoices and
    GET /default-voices. Edge TTS voices are language-coded strings (see
    EDGE_VOICES in tts.py); ElevenLabs voice IDs come from the ElevenLabs
    dashboard.
    """
    provider = (args.provider or "").lower()
    if provider not in ("60db", "sixtydb"):
        print("  Error: --provider 60db is the only listing currently supported.")
        print("  Edge voices: see EDGE_VOICES in verticals/tts.py.")
        print("  ElevenLabs voices: https://elevenlabs.io/app/voice-library")
        sys.exit(1)

    import requests
    from .config import get_60db_key

    api_key = get_60db_key()
    if not api_key:
        print("  Error: SIXTYDB_API_KEY not set. Run setup or export the env var.")
        sys.exit(1)

    headers = {"Authorization": f"Bearer {api_key}"}
    endpoints = [
        ("Default voices", "https://api.60db.ai/default-voices"),
        ("My voices",      "https://api.60db.ai/myvoices"),
    ]

    def _print_voice_row(v: dict):
        labels = v.get("labels") or {}
        lang = labels.get("language_name") or labels.get("language") or "?"
        gender = labels.get("gender") or "?"
        accent = labels.get("accent") or "?"
        model = v.get("model") or "?"
        category = v.get("category") or "?"
        name = v.get("name") or "?"
        vid = v.get("voice_id") or "?"
        print(f"    {vid}  {name:18.18}  {lang:10.10}  {gender:6.6}  {accent:10.10}  {model:14.14}  {category}")

    for title, url in endpoints:
        try:
            r = requests.get(url, headers=headers, timeout=30)
        except Exception as exc:
            print(f"\n  {title}: request failed — {exc}")
            continue
        if r.status_code != 200:
            print(f"\n  {title}: HTTP {r.status_code} — {r.text[:120]}")
            continue
        body = r.json()
        items = body.get("data") or []
        print(f"\n  {title} ({len(items)}):")
        if not items:
            print("    (none)")
            continue
        print(f"    {'voice_id':36}  {'name':18}  {'language':10}  {'gender':6}  {'accent':10}  {'model':14}  category")
        print(f"    {'-' * 36}  {'-' * 18}  {'-' * 10}  {'-' * 6}  {'-' * 10}  {'-' * 14}  {'-' * 8}")
        for v in items:
            _print_voice_row(v)


def cmd_serve(args):
    from .server import create_app

    app = create_app()
    app.run(host=args.host, port=args.port, debug=args.debug)


def main():
    parser = argparse.ArgumentParser(
        description="Verticals v3 — AI-Native Vertical Video Engine",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Docs: https://github.com/rushindrasinha/verticals\n"
               "Product: https://verticals.gg",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Enable debug logging")
    sub = parser.add_subparsers(dest="cmd")

    # Shared niche/provider args
    niche_help = f"Content niche ({', '.join(list_niches()[:8])}...)"

    # draft
    p_draft = sub.add_parser("draft", help="Generate script + metadata")
    p_draft.add_argument("--topic", "--news", dest="news", required=False, help="Topic/news headline")
    p_draft.add_argument("--context", default="", help="Channel context")
    p_draft.add_argument("--niche", default="general", help=niche_help)
    p_draft.add_argument("--platform", default="shorts", choices=["shorts", "reels", "tiktok", "all"])
    p_draft.add_argument("--provider", default=None, help="LLM: claude, gemini, openai, ollama")
    p_draft.add_argument("--discover", action="store_true", help="Use topic engine")
    p_draft.add_argument("--auto-pick", action="store_true", help="Let LLM pick the best topic")
    p_draft.add_argument("--dry-run", action="store_true", help="Draft only")

    # produce
    p_produce = sub.add_parser("produce", help="Generate video from draft")
    p_produce.add_argument("--draft", required=True)
    p_produce.add_argument("--lang", default="en", choices=["en", "hi", "es", "pt", "de", "fr", "ja", "ko"])
    p_produce.add_argument("--voice", default=None, help="TTS: edge, elevenlabs, 60db, say")
    p_produce.add_argument("--script", default=None, help="Override script text")
    p_produce.add_argument("--force", action="store_true", help="Redo all stages")

    # upload
    p_upload = sub.add_parser("upload", help="Upload to YouTube")
    p_upload.add_argument("--draft", required=True)
    p_upload.add_argument("--lang", default="en", choices=["en", "hi", "es", "pt", "de", "fr", "ja", "ko"])
    p_upload.add_argument("--force", action="store_true", help="Re-upload even if done")

    # run (full pipeline)
    p_run = sub.add_parser("run", help="Full pipeline: draft -> produce -> upload")
    p_run.add_argument("--topic", "--news", dest="news", required=False, help="Topic/news headline")
    p_run.add_argument("--niche", default="general", help=niche_help)
    p_run.add_argument("--platform", default="shorts", choices=["shorts", "reels", "tiktok", "all"])
    p_run.add_argument("--provider", default=None, help="LLM: claude, gemini, openai, ollama")
    p_run.add_argument("--voice", default=None, help="TTS: edge, elevenlabs, 60db, say")
    p_run.add_argument("--lang", default="en", choices=["en", "hi", "es", "pt", "de", "fr", "ja", "ko"])
    p_run.add_argument("--dry-run", action="store_true")
    p_run.add_argument("--context", default="")
    p_run.add_argument("--discover", action="store_true")
    p_run.add_argument("--auto-pick", action="store_true")

    # topics
    p_topics = sub.add_parser("topics", help="Discover trending topics")
    p_topics.add_argument("--niche", default="general", help=niche_help)
    p_topics.add_argument("--limit", type=int, default=15, help="Max topics to show")

    # harvest
    p_harvest = sub.add_parser("harvest", help="Harvest licensed YouTube and Reddit candidates for a draft")
    p_harvest.add_argument("--draft", required=True, help="Draft JSON path")
    p_harvest.add_argument("--niche", default=None, help="Override niche for query generation")
    p_harvest.add_argument("--results", type=int, default=8, help="Search results per generated query")
    p_harvest.add_argument("--downloads", type=int, default=6, help="Max candidate clips to download")

    # niches
    sub.add_parser("niches", help="List available niche profiles")

    # voices
    p_voices = sub.add_parser("voices", help="List TTS voices (currently: 60db)")
    p_voices.add_argument("--provider", default="60db", help="TTS provider (only '60db' supported)")

    # serve
    p_serve = sub.add_parser("serve", help="Run the Flask backend")
    p_serve.add_argument("--host", default="127.0.0.1")
    p_serve.add_argument("--port", type=int, default=5000)
    p_serve.add_argument("--debug", action="store_true")

    args = parser.parse_args()

    if args.verbose:
        set_verbose(True)

    if not args.cmd:
        parser.print_help()
        return

    # Handle utility commands that don't need first-run setup
    if args.cmd == "niches":
        cmd_niches(args)
        return
    if args.cmd == "voices":
        cmd_voices(args)
        return
    if args.cmd == "serve":
        cmd_serve(args)
        return

    maybe_run_setup(args)

    # Handle --discover flag for draft/run
    if args.cmd in ("draft", "run") and getattr(args, "discover", False):
        from .topics import TopicEngine
        niche = getattr(args, "niche", "general") or "general"
        engine = TopicEngine(niche=niche)
        candidates = engine.discover(limit=15)
        if not candidates:
            print("  No trending topics found. Use --topic instead.")
            sys.exit(1)

        if getattr(args, "auto_pick", False):
            args.news = engine.auto_pick(candidates)
            print(f"  Auto-picked: {args.news}")
        else:
            print("\n  Trending topics:\n")
            for i, t in enumerate(candidates, 1):
                print(f"  {i:2d}. [{t.source}] {t.title}")
            choice = input("\n  Pick a number (or enter custom topic): ").strip()
            if choice.isdigit() and 1 <= int(choice) <= len(candidates):
                args.news = candidates[int(choice) - 1].title
            else:
                args.news = choice
    elif args.cmd in ("draft", "run") and not getattr(args, "news", None):
        print("  Error: --topic or --discover required")
        sys.exit(1)

    if args.cmd == "draft":
        cmd_draft(args)
    elif args.cmd == "produce":
        cmd_produce(args)
    elif args.cmd == "upload":
        cmd_upload(args)
    elif args.cmd == "run":
        cmd_run(args)
    elif args.cmd == "topics":
        cmd_topics(args)
    elif args.cmd == "harvest":
        cmd_harvest(args)


if __name__ == "__main__":
    main()
