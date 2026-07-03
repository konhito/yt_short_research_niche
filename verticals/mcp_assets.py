"""Asset helpers backed by MCP servers."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import requests

from .config import SKILL_DIR, get_pexels_key, get_pixabay_key
from .log import log
from .mcp_bridge import call_mcp_tool, extract_urls, parse_tool_payload


VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}


def _download(url: str, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    response = requests.get(url, stream=True, timeout=120)
    response.raise_for_status()
    with out_path.open("wb") as f:
        for chunk in response.iter_content(chunk_size=1024 * 256):
            if chunk:
                f.write(chunk)
    return out_path


def _first_matching_url(payload, suffixes: tuple[str, ...]) -> str | None:
    urls = extract_urls(payload)
    for url in urls:
        lowered = url.lower()
        if any(lowered.split("?")[0].endswith(suffix) for suffix in suffixes):
            return url
    return None


def fetch_pexels_footage(
    query: str, out_dir: Path, limit: int = 3, selection_seed: str = ""
) -> list[Path]:
    """Search Pexels videos directly via REST and download portrait clips."""
    api_key = get_pexels_key()
    if not api_key:
        raise RuntimeError("PEXELS_API_KEY is required for Pexels footage")

    log(f"Searching Pexels footage for: {query}")
    response = requests.get(
        "https://api.pexels.com/videos/search",
        params={
            "query": query,
            "per_page": max(limit * 3, limit),
            "orientation": "portrait",
        },
        headers={"Authorization": api_key},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    video_urls: list[str] = []
    for video in payload.get("videos", []):
        files = video.get("video_files", []) or []
        files = sorted(
            files,
            key=lambda f: (
                0 if int(f.get("height") or 0) >= int(f.get("width") or 0) else 1,
                -int(f.get("height") or 0),
            ),
        )
        for file in files:
            url = str(file.get("link", ""))
            if url.lower().split("?")[0].endswith((".mp4", ".mov", ".m4v", ".webm")):
                video_urls.append(url)
                break
    if not video_urls:
        raise RuntimeError("Pexels returned no downloadable video URLs")

    selected_urls = _rotated_selection(video_urls, limit, selection_seed)
    clips: list[Path] = []
    for i, url in enumerate(selected_urls, start=1):
        clip_path = out_dir / f"pexels_{i}.mp4"
        log(f"Downloading Pexels clip {i}/{min(limit, len(video_urls))}")
        clips.append(_download(url, clip_path))

    return clips


def fetch_pixabay_footage(
    query: str, out_dir: Path, limit: int = 3, selection_seed: str = ""
) -> list[Path]:
    """Search Pixabay videos and download portrait-friendly clips."""
    api_key = get_pixabay_key()
    if not api_key:
        raise RuntimeError("PIXABAY_API_KEY is required for Pixabay footage")

    log(f"Searching Pixabay footage for: {query}")
    response = requests.get(
        "https://pixabay.com/api/videos/",
        params={
            "key": api_key,
            "q": query,
            "video_type": "film",
            "safesearch": "true",
            "per_page": max(limit * 3, limit),
            "order": "popular",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()

    video_urls: list[str] = []
    for hit in payload.get("hits", []):
        variants = list((hit.get("videos") or {}).values())
        variants = sorted(
            variants,
            key=lambda item: (
                0 if int(item.get("height") or 0) >= int(item.get("width") or 0) else 1,
                -int(item.get("height") or 0),
            ),
        )
        for variant in variants:
            url = str(variant.get("url", ""))
            if url.lower().split("?")[0].endswith(tuple(VIDEO_SUFFIXES)):
                video_urls.append(url)
                break
    if not video_urls:
        raise RuntimeError("Pixabay returned no downloadable video URLs")

    selected_urls = _rotated_selection(video_urls, limit, selection_seed)
    clips: list[Path] = []
    for i, url in enumerate(selected_urls, start=1):
        clip_path = out_dir / f"pixabay_{i}.mp4"
        log(f"Downloading Pixabay clip {i}/{min(limit, len(video_urls))}")
        clips.append(_download(url, clip_path))
    return clips


def _rotated_selection(urls: list[str], limit: int, seed: str) -> list[str]:
    """Rotate ranked results so independent jobs do not always take item zero."""
    if not urls or not seed:
        return urls[:limit]
    offset = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16) % len(urls)
    return (urls[offset:] + urls[:offset])[:limit]


def fetch_local_footage(
    query: str,
    out_dir: Path,
    niche: str = "general",
    limit: int = 1,
    roots: list[Path] | None = None,
) -> list[Path]:
    """Copy reusable local clips matching the query into the work directory."""
    if roots is None:
        repo_root = Path(__file__).resolve().parent.parent
        roots = [repo_root / "assets", SKILL_DIR / "assets"]
    candidates: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        for subdir in (root / niche, root / "common", root):
            if subdir.exists():
                candidates.extend(path for path in subdir.rglob("*") if path.suffix.lower() in VIDEO_SUFFIXES)
    if not candidates:
        return []

    tokens = _asset_tokens(query)
    ranked = sorted(candidates, key=lambda path: (-_asset_score(path, tokens), str(path)))
    selected = [path for path in ranked if _asset_score(path, tokens) > 0][:limit]
    if not selected:
        selected = ranked[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for index, source in enumerate(selected, start=1):
        dest = out_dir / f"local_{index}{source.suffix.lower()}"
        shutil.copy2(source, dest)
        copied.append(dest)
    if copied:
        log(f"Using {len(copied)} local asset clip(s) for: {query}")
    return copied


def _asset_tokens(text: str) -> set[str]:
    return {
        token
        for token in "".join(ch.lower() if ch.isalnum() else " " for ch in text).split()
        if len(token) > 2
    }


def _asset_score(path: Path, tokens: set[str]) -> int:
    haystack = " ".join(part.lower().replace("_", " ").replace("-", " ") for part in path.parts)
    return sum(1 for token in tokens if token in haystack)


def fetch_meme_image(
    template_numeric_id: str,
    text0: str,
    text1: str,
    out_dir: Path,
) -> Path:
    """Generate a meme image via MCP and download the returned asset."""
    log(f"Generating meme thumbnail via MCP template={template_numeric_id}")
    result = call_mcp_tool(
        "meme",
        "generateMeme",
        {
            "templateNumericId": int(template_numeric_id),
            "text0": text0,
            "text1": text1,
        },
    )
    payload = parse_tool_payload(result)
    url = _first_matching_url(payload, (".png", ".jpg", ".jpeg", ".webp")) or _first_matching_url(payload, ())
    if not url:
        urls = extract_urls(payload)
        if urls:
            url = urls[0]
    if not url:
        raise RuntimeError("Meme MCP returned no downloadable image URL")

    out_path = out_dir / "meme_thumbnail.png"
    return _download(url, out_path)
