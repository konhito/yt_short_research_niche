"""Parallel orchestration for independent harvested-video sources."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .log import log
from .reddit_harvest import harvest_reddit_videos
from .video_candidates import deduplicate_candidates
from .yt_harvest import harvest_topic_shorts


def harvest_video_sources(
    draft: dict,
    work_dir: Path,
    *,
    niche: str,
    editing: dict,
    subreddits: list[str] | None = None,
) -> dict:
    """Harvest YouTube and Reddit independently, then merge/deduplicate."""
    youtube_limit = int(editing.get("youtube_clips", [4, 8])[1])
    reddit_limit = int(editing.get("reddit_clips", [4, 8])[1])
    with ThreadPoolExecutor(max_workers=2) as executor:
        youtube_future = executor.submit(
            harvest_topic_shorts,
            draft,
            work_dir / "harvested_shorts",
            niche=niche,
            max_results=int(editing.get("yt_harvest_results", 30)),
            max_downloads=youtube_limit,
        )
        reddit_future = executor.submit(
            harvest_reddit_videos,
            draft,
            work_dir / "harvested_reddit",
            niche=niche,
            subreddits=subreddits,
            max_results=int(editing.get("reddit_harvest_results", 25)),
            max_downloads=reddit_limit,
            after=str(editing.get("reddit_harvest_after", "30d")),
        )
        results = {}
        for name, future in (("youtube", youtube_future), ("reddit", reddit_future)):
            try:
                results[name] = future.result()
            except Exception as exc:
                log(f"{name.title()} harvest failed: {exc}")
                results[name] = {"assets": [], "rejected": [{"reason": str(exc)}], "manifest_path": ""}
    assets = deduplicate_candidates(results["youtube"].get("assets", []) + results["reddit"].get("assets", []))
    return {
        "assets": assets,
        "rejected": results["youtube"].get("rejected", []) + results["reddit"].get("rejected", []),
        "manifests": {
            "youtube": results["youtube"].get("manifest_path", ""),
            "reddit": results["reddit"].get("manifest_path", ""),
        },
        "source_counts": {
            "youtube_harvest": sum(item.get("source") == "youtube_harvest" for item in assets),
            "reddit_harvest": sum(item.get("source") == "reddit_harvest" for item in assets),
        },
    }
