"""Topic-aware YouTube Shorts harvesting via yt-dlp."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .asset_history import filter_fresh_candidates
from .log import log
from .video_candidates import deduplicate_candidates, enrich_candidate, normalize_candidate
from .search_tags import normalize_search_tags


def build_shorts_queries(draft: dict, niche: str = "general", max_queries: int = 8) -> list[str]:
    """Generate vetted yt-dlp search queries from the actual draft/script."""
    if draft.get("search_tags"):
        return [f"{tag} shorts" for tag in normalize_search_tags(draft)][:max_queries]
    text = " ".join(str(draft.get(key, "")) for key in ("youtube_title", "news", "script"))
    entities = _extract_entities(text)
    queries: list[str] = []
    if entities:
        joined = " ".join(entities[:3])
        queries.extend([
            f"{joined} shorts",
            f"{joined} reaction shorts",
        ])
    if draft.get("news"):
        queries.append(f"{draft['news']} shorts")
    return _dedupe(queries)[:max_queries]


def parse_yt_dlp_json_lines(output: str) -> list[dict]:
    items = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            items.append(payload)
    return items


def score_candidate(candidate: dict, draft: dict, query: str) -> int:
    """Score metadata before download so bad search results are rejected."""
    title = str(candidate.get("title", "")).lower()
    url = str(candidate.get("webpage_url", "")).lower()
    duration = int(candidate.get("duration") or 0)
    draft_text = " ".join(str(draft.get(key, "")) for key in ("youtube_title", "news", "script")).lower()
    keywords = _keyword_tokens(draft_text + " " + query)
    score = 0
    for token in keywords:
        if token in title:
            score += 3
    if "shorts" in url or "#short" in title or "shorts" in title:
        score += 8
    if 5 <= duration <= 90:
        score += 6
    elif duration > 180:
        score -= 10
    if "gta 5" in title and "gta 6" in draft_text:
        score -= 8
    if any(spam in title for spam in ("compilation", "full movie", "live stream")):
        score -= 4
    return score


def harvest_topic_shorts(
    draft: dict,
    out_dir: Path,
    niche: str = "general",
    max_results: int = 8,
    max_downloads: int = 6,
    min_score: int = 8,
    history_path: Path | None = None,
) -> dict[str, Any]:
    """Search metadata, score candidates, download selected Shorts, save manifest."""
    base_cmd = _yt_dlp_base_cmd()
    if not base_cmd:
        log("yt-dlp not installed - skipping YouTube Shorts harvest")
        return {"assets": [], "rejected": [], "queries": [], "manifest_path": ""}
    out_dir.mkdir(parents=True, exist_ok=True)
    queries = build_shorts_queries(draft, niche=niche)
    seen: set[str] = set()
    candidates = []
    rejected = []
    for query in queries:
        search_ref = f"ytsearch{max_results}:{query}"
        result = subprocess.run(
            [*base_cmd, search_ref, "--dump-json", "--skip-download", "--no-playlist"],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if result.returncode != 0:
            rejected.append({"query": query, "reason": result.stderr[:200] or "yt-dlp search failed"})
            continue
        for item in parse_yt_dlp_json_lines(result.stdout):
            url = str(item.get("webpage_url") or item.get("url") or "")
            if not url or url in seen:
                continue
            seen.add(url)
            score = score_candidate(item, draft, query)
            record = _candidate_record(item, query, score)
            if score >= min_score:
                candidates.append(record)
            else:
                record["reason"] = "low relevance score"
                rejected.append(record)

    candidates.sort(key=lambda item: (-item["relevance_score"], item["duration"], item["title"]))
    selected, reused_rejections = filter_fresh_candidates(
        candidates,
        max_items=max_downloads,
        recent_jobs=10,
        history_path=history_path,
    )
    rejected.extend(reused_rejections)
    assets = []
    for candidate in selected:
        clip_dir = out_dir / _safe_slug(candidate["id"] or candidate["title"])
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
            failed = {**candidate, "reason": result.stderr[:200] or "yt-dlp download failed"}
            rejected.append(failed)
            continue
        clip_path = _find_downloaded_clip(clip_dir)
        if not clip_path:
            rejected.append({**candidate, "reason": "download completed but clip file was not found"})
            continue
        asset = normalize_candidate({
            "source": "youtube_harvest",
            "source_id": candidate["id"],
            "path": str(clip_path),
            "query": candidate["title"],
            "search_query": candidate["query"],
            "topic_query": draft.get("news") or draft.get("youtube_title", ""),
            "title": candidate["title"],
            "url": candidate["url"],
            "uploader": candidate.get("uploader", ""),
            "duration": candidate.get("duration", 0),
            "relevance_score": candidate["relevance_score"],
            "status": "candidate",
            "protected": False,
            "asset_role": "harvested_short",
            "effect": "hard_cut",
            "fit": "cover_crop",
        })
        try:
            asset = enrich_candidate(asset)
        except Exception as exc:
            asset["enrichment_error"] = str(exc)
        assets.append(asset)

    assets = deduplicate_candidates(assets)

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queries": queries,
        "assets": assets,
        "rejected": rejected,
    }
    manifest_path = out_dir / "harvest_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"YouTube Shorts harvest: downloaded {len(assets)} candidate clip(s), rejected {len(rejected)}")
    return {**manifest, "manifest_path": str(manifest_path)}


def _yt_dlp_base_cmd() -> list[str]:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    try:
        import yt_dlp  # noqa: F401
    except Exception:
        return []
    return [sys.executable, "-m", "yt_dlp"]


def _candidate_record(item: dict, query: str, score: int) -> dict:
    return {
        "source": "youtube_harvest",
        "source_id": str(item.get("id", "")),
        "id": str(item.get("id", "")),
        "title": str(item.get("title", "")),
        "url": str(item.get("webpage_url") or item.get("url") or ""),
        "duration": int(item.get("duration") or 0),
        "uploader": str(item.get("uploader", "")),
        "query": query,
        "relevance_score": score,
    }


def _find_downloaded_clip(directory: Path) -> Path | None:
    for suffix in ("*.mp4", "*.mov", "*.m4v", "*.webm", "*.mkv"):
        matches = sorted(directory.glob(suffix))
        if matches:
            return matches[0]
    return None


def _extract_entities(text: str) -> list[str]:
    raw = re.findall(r"\b(?:[A-Z][A-Za-z0-9]+|GTA|AI|PS5|Xbox|Rockstar|Nintendo)\b", text)
    merged = []
    for item in raw:
        if item.lower() not in {"the", "and", "this", "what"}:
            merged.append(item)
    return _dedupe(merged)


def _keyword_tokens(text: str) -> set[str]:
    stop = {"the", "and", "for", "with", "this", "that", "shorts", "reaction"}
    return {
        token
        for token in re.sub(r"[^a-zA-Z0-9]+", " ", text.lower()).split()
        if len(token) > 2 and token not in stop
    }


def _safe_slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.strip())[:80].strip("_")
    return slug or "clip"


def _dedupe(items: list[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result
