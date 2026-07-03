"""PullPush Reddit video discovery and yt-dlp harvesting."""

from __future__ import annotations

import json
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests

from .asset_history import filter_fresh_candidates
from .log import log
from .video_candidates import deduplicate_candidates, enrich_candidate, normalize_candidate
from .yt_harvest import _yt_dlp_base_cmd
from .search_tags import normalize_search_tags


PULLPUSH_SUBMISSION_URL = "https://api.pullpush.io/reddit/search/submission/"


def build_reddit_queries(draft: dict, niche: str = "general", max_queries: int = 6) -> list[str]:
    if draft.get("search_tags"):
        return normalize_search_tags(draft)[:max_queries]
    text = " ".join(str(draft.get(key, "")) for key in ("youtube_title", "news", "script"))
    lowered = text.lower()
    queries = []
    entities = re.findall(r"\b(?:[A-Z][A-Za-z0-9]+|GTA|AI|PS5|Xbox|Rockstar|Nintendo)\b", text)
    entities = [item for item in _dedupe(entities) if item.lower() not in {"the", "and", "this"}]
    if entities:
        queries.append(" ".join(entities[:3]))
    if draft.get("news"):
        queries.append(str(draft["news"]))
    return _dedupe(queries)[:max_queries]


def search_reddit_videos(
    query: str,
    subreddits: list[str],
    *,
    size: int = 25,
    after: str = "30d",
) -> list[dict]:
    results = []
    for subreddit in subreddits:
        response = requests.get(
            PULLPUSH_SUBMISSION_URL,
            params={
                "q": query,
                "subreddit": subreddit,
                "is_video": "true",
                "over_18": "false",
                "after": after,
                "sort": "desc",
                "sort_type": "score",
                "size": min(int(size), 100),
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        results.extend(item for item in payload.get("data", []) if isinstance(item, dict))
    return results


def score_reddit_candidate(candidate: dict, draft: dict, query: str) -> int:
    title = str(candidate.get("title", "")).lower()
    draft_text = " ".join(str(draft.get(key, "")) for key in ("youtube_title", "news", "script")).lower()
    tokens = _keyword_tokens(draft_text + " " + query)
    score = sum(3 for token in tokens if token in title)
    if candidate.get("is_video") or "v.redd.it" in str(candidate.get("url", "")):
        score += 8
    if str(candidate.get("subreddit", "")).lower() in {"gaming", "games", "pcgaming", "gta6", "gta"}:
        score += 5
    score += min(8, int(math.log10(max(1, int(candidate.get("score") or 0)))) * 2)
    score += min(5, int(math.log10(max(1, int(candidate.get("num_comments") or 0)))) * 2)
    if "gta 5" in title and "gta 6" in draft_text:
        score -= 10
    if any(term in title for term in ("mod compilation", "full stream", "walkthrough part")):
        score -= 5
    return score


def harvest_reddit_videos(
    draft: dict,
    out_dir: Path,
    *,
    niche: str = "general",
    subreddits: list[str] | None = None,
    max_results: int = 25,
    max_downloads: int = 8,
    min_score: int = 8,
    after: str = "30d",
    history_path: Path | None = None,
) -> dict:
    base_cmd = _yt_dlp_base_cmd()
    queries = build_reddit_queries(draft, niche=niche)
    if not base_cmd:
        log("yt-dlp not installed - skipping Reddit video harvest")
        return {"queries": queries, "assets": [], "rejected": [], "manifest_path": ""}
    subreddits = subreddits or (["gaming", "Games", "pcgaming", "GTA6"] if niche == "gaming" else [niche])
    out_dir.mkdir(parents=True, exist_ok=True)
    candidates = []
    rejected = []
    seen_ids = set()
    for query in queries:
        try:
            submissions = search_reddit_videos(query, subreddits, size=max_results, after=after)
        except Exception as exc:
            rejected.append({"query": query, "reason": f"PullPush search failed: {exc}"})
            continue
        for submission in submissions:
            source_id = str(submission.get("id", ""))
            if not source_id or source_id in seen_ids:
                continue
            seen_ids.add(source_id)
            score = score_reddit_candidate(submission, draft, query)
            record = _submission_record(submission, query, score)
            if score >= min_score and record["url"]:
                candidates.append(record)
            else:
                rejected.append({**record, "reason": "low relevance score or missing video URL"})

    candidates.sort(key=lambda item: (-item["relevance_score"], -item.get("reddit_score", 0)))
    selected, reused_rejections = filter_fresh_candidates(
        candidates,
        max_items=max_downloads,
        recent_jobs=10,
        history_path=history_path,
    )
    rejected.extend(reused_rejections)
    workers = min(6, max(1, len(selected)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        downloaded = list(executor.map(lambda item: _download_candidate(item, out_dir, base_cmd), selected))
    assets = []
    for candidate, result in zip(selected, downloaded):
        if isinstance(result, Path):
            asset = normalize_candidate({**candidate, "path": str(result), "protected": False})
            try:
                asset = enrich_candidate(asset)
            except Exception as exc:
                asset["enrichment_error"] = str(exc)
            assets.append(asset)
        else:
            rejected.append({**candidate, "reason": str(result)})
    assets = deduplicate_candidates(assets)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queries": queries,
        "subreddits": subreddits,
        "assets": assets,
        "rejected": rejected,
    }
    manifest_path = out_dir / "reddit_harvest_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Reddit harvest: downloaded {len(assets)} candidate clip(s), rejected {len(rejected)}")
    return {**manifest, "manifest_path": str(manifest_path)}


def _submission_record(item: dict, query: str, score: int) -> dict:
    permalink = str(item.get("permalink", ""))
    reddit_url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink
    media_url = str(item.get("url") or item.get("url_overridden_by_dest") or "")
    return {
        "source": "reddit_harvest",
        "source_id": str(item.get("id", "")),
        "title": str(item.get("title", "")),
        "url": reddit_url or media_url,
        "media_url": media_url,
        "query": str(item.get("title", "")),
        "search_query": query,
        "topic_query": query,
        "subreddit": str(item.get("subreddit", "")),
        "reddit_score": int(item.get("score") or 0),
        "num_comments": int(item.get("num_comments") or 0),
        "created_utc": int(item.get("created_utc") or 0),
        "relevance_score": score,
    }


def _download_candidate(candidate: dict, out_dir: Path, base_cmd: list[str]) -> Path | str:
    clip_dir = out_dir / candidate["source_id"]
    clip_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(clip_dir / "%(id)s.%(ext)s")
    result = subprocess.run(
        [
            *base_cmd,
            candidate["url"],
            "-f",
            "bv*[height<=1920]+ba/b[height<=1920]/b",
            "--merge-output-format",
            "mp4",
            "--no-playlist",
            "-o",
            output_template,
        ],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        return result.stderr[:300] or "yt-dlp Reddit download failed"
    for suffix in ("*.mp4", "*.mov", "*.m4v", "*.webm", "*.mkv"):
        matches = sorted(clip_dir.glob(suffix))
        if matches:
            return matches[0]
    return "download completed but clip file was not found"


def _keyword_tokens(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "this", "that", "from", "about"}
    return {
        token
        for token in re.sub(r"[^a-zA-Z0-9]+", " ", text.lower()).split()
        if len(token) > 2 and token not in stop
    }


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = item.lower().strip()
        if key and key not in seen:
            seen.add(key)
            result.append(item.strip())
    return result
