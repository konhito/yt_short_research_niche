"""Topic-aware Vimeo discovery and download through yt-dlp."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote_plus

import requests

from .asset_history import filter_fresh_candidates
from .config import get_vimeo_key
from .log import log
from .search_tags import normalize_search_tags
from .video_candidates import deduplicate_candidates, enrich_candidate, normalize_candidate
from .yt_harvest import score_candidate


def build_vimeo_queries(draft: dict, niche: str = "general", max_queries: int = 6) -> list[str]:
    tags = normalize_search_tags(draft)
    if tags:
        return tags[:max_queries]
    title = str(draft.get("youtube_title") or draft.get("news") or "").strip()
    return [title] if title else []


def discover_vimeo_api(query: str, token: str, limit: int = 20) -> list[dict]:
    response = requests.get(
        "https://api.vimeo.com/videos",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.vimeo.*+json;version=3.4"},
        params={"query": query, "per_page": limit, "sort": "relevant", "direction": "desc", "filter": "playable"},
        timeout=30,
    )
    response.raise_for_status()
    results = []
    for item in response.json().get("data", []):
        source_id = str(item.get("uri", "")).rstrip("/").split("/")[-1]
        url = str(item.get("link") or (f"https://vimeo.com/{source_id}" if source_id else ""))
        if not source_id or not url:
            continue
        results.append({
            "source": "vimeo_harvest",
            "source_id": source_id,
            "id": source_id,
            "title": str(item.get("name", "")),
            "url": url,
            "duration": int(item.get("duration") or 0),
            "uploader": str((item.get("user") or {}).get("name", "")),
            "query": query,
        })
    return results


def extract_vimeo_urls(html: str) -> list[str]:
    ids = re.findall(r'(?:href=["\'](?:https?://(?:www\.)?vimeo\.com)?/)(\d{6,12})(?:[?"\'/])', html)
    seen = set()
    urls = []
    for source_id in ids:
        if source_id not in seen:
            seen.add(source_id)
            urls.append(f"https://vimeo.com/{source_id}")
    return urls


def discover_vimeo_html(query: str, limit: int, base_cmd: list[str]) -> list[dict]:
    response = requests.get(
        f"https://vimeo.com/search?type=clip&q={quote_plus(query)}&duration=short",
        headers={"User-Agent": "Mozilla/5.0 (compatible; verticals-assets/3.1)"},
        timeout=30,
    )
    response.raise_for_status()
    results = []
    for url in extract_vimeo_urls(response.text)[:limit]:
        process = subprocess.run(
            [*base_cmd, url, "--dump-single-json", "--skip-download", "--no-playlist"],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=60, check=False,
        )
        if process.returncode != 0:
            continue
        try:
            item = json.loads(process.stdout)
        except json.JSONDecodeError:
            continue
        source_id = str(item.get("id") or url.rstrip("/").split("/")[-1])
        results.append({
            "source": "vimeo_harvest", "source_id": source_id, "id": source_id,
            "title": str(item.get("title", "")), "url": str(item.get("webpage_url") or url),
            "duration": int(item.get("duration") or 0), "uploader": str(item.get("uploader", "")),
            "query": query,
        })
    return results


def harvest_vimeo_clips(
    draft: dict,
    out_dir: Path,
    niche: str = "general",
    max_results: int = 20,
    max_downloads: int = 4,
    min_score: int = 6,
    history_path: Path | None = None,
) -> dict:
    base_cmd = _yt_dlp_base_cmd()
    if not base_cmd:
        log("yt-dlp not installed - skipping Vimeo harvest")
        return {"assets": [], "rejected": [], "queries": [], "manifest_path": ""}
    out_dir.mkdir(parents=True, exist_ok=True)
    token = get_vimeo_key()
    queries = build_vimeo_queries(draft, niche=niche)
    candidates = []
    rejected = []
    seen = set()
    for query in queries:
        try:
            found = discover_vimeo_api(query, token, max_results) if token else discover_vimeo_html(query, max_results, base_cmd)
        except Exception as exc:
            rejected.append({"query": query, "reason": str(exc)})
            continue
        for item in found:
            if item["url"] in seen:
                continue
            seen.add(item["url"])
            metadata = {**item, "webpage_url": item["url"]}
            item["relevance_score"] = score_candidate(metadata, draft, query)
            if item["relevance_score"] >= min_score:
                candidates.append(item)
            else:
                rejected.append({**item, "reason": "low relevance score"})

    candidates.sort(key=lambda item: (-item["relevance_score"], item.get("duration", 0)))
    selected, reused = filter_fresh_candidates(
        candidates, max_items=max_downloads, recent_jobs=10, history_path=history_path,
    )
    rejected.extend(reused)
    assets = []
    for candidate in selected:
        clip_dir = out_dir / _safe_slug(candidate["source_id"] or candidate["title"])
        clip_dir.mkdir(parents=True, exist_ok=True)
        output_template = str(clip_dir / "%(id)s.%(ext)s")
        process = subprocess.run(
            [*base_cmd, candidate["url"], "-f", "bv*[height<=1920]+ba/b[height<=1920]/b",
             "--merge-output-format", "mp4", "--no-playlist", "-o", output_template],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300, check=False,
        )
        if process.returncode != 0:
            rejected.append({**candidate, "reason": process.stderr[:200] or "yt-dlp download failed"})
            continue
        clip_path = _find_downloaded_clip(clip_dir)
        if not clip_path:
            rejected.append({**candidate, "reason": "download completed but clip file was not found"})
            continue
        asset = normalize_candidate({
            **candidate,
            "path": str(clip_path),
            "search_query": candidate["query"],
            "topic_query": draft.get("news") or draft.get("youtube_title", ""),
            "status": "candidate", "protected": False, "asset_role": "harvested_vimeo",
            "effect": "hard_cut", "fit": "cover_crop",
        })
        try:
            asset = enrich_candidate(asset)
        except Exception as exc:
            asset["enrichment_error"] = str(exc)
        assets.append(asset)

    assets = deduplicate_candidates(assets)
    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "queries": queries, "assets": assets, "rejected": rejected,
    }
    manifest_path = out_dir / "harvest_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    log(f"Vimeo harvest: downloaded {len(assets)} candidate clip(s), rejected {len(rejected)}")
    return {**manifest, "manifest_path": str(manifest_path)}


def _yt_dlp_base_cmd() -> list[str]:
    if shutil.which("yt-dlp"):
        return ["yt-dlp"]
    try:
        import yt_dlp  # noqa: F401
    except Exception:
        return []
    return [sys.executable, "-m", "yt_dlp"]


def _find_downloaded_clip(directory: Path) -> Path | None:
    for pattern in ("*.mp4", "*.mov", "*.m4v", "*.webm", "*.mkv"):
        matches = sorted(directory.glob(pattern))
        if matches:
            return matches[0]
    return None


def _safe_slug(value: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", value).strip("_")[:80] or "clip"
