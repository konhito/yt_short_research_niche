"""Download and validate images discovered from top research pages."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image

from .log import log
from .research import discover_search_tag_images


def discover_and_download_research_images(
    search_tags: list[str],
    existing_candidates: list[dict],
    out_dir: Path,
    limit: int = 6,
    niche: str = "general",
) -> list[dict]:
    """Discover web images using shared tags, then download one combined pool."""
    discovered = discover_search_tag_images(search_tags, niche=niche, limit=limit)
    combined = []
    seen = set()
    for candidate in discovered + list(existing_candidates or []):
        image_url = str(candidate.get("image_url", ""))
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        combined.append(candidate)
    return download_research_images(combined, out_dir, limit)


def download_research_images(candidates: list[dict], out_dir: Path, limit: int = 6) -> list[dict]:
    selected = candidates[:limit]
    if not selected:
        return []
    out_dir.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=min(6, len(selected))) as executor:
        futures = [executor.submit(_download_one, candidate, out_dir, index) for index, candidate in enumerate(selected)]
        results = [future.result() for future in futures]
    assets = [asset for asset in results if asset]
    log(f"Research images: downloaded {len(assets)}/{len(selected)} relevant image(s)")
    return assets


def _download_one(candidate: dict, out_dir: Path, index: int) -> dict | None:
    try:
        response = requests.get(
            candidate["image_url"],
            headers={"User-Agent": "Mozilla/5.0 (compatible; verticals-assets/3.1)"},
            timeout=30,
        )
        response.raise_for_status()
        image = Image.open(BytesIO(response.content)).convert("RGB")
        if image.width < 400 or image.height < 300:
            return None
        path = out_dir / f"research_{index:02d}.jpg"
        image.save(path, quality=92)
        return {
            "type": "research_image",
            "source": "web_research",
            "path": str(path),
            "query": str(candidate.get("title", "Relevant research image")),
            "title": str(candidate.get("title", "")),
            "url": str(candidate.get("source_url", "")),
            "image_url": str(candidate.get("image_url", "")),
            "width": image.width,
            "height": image.height,
            "effect": "pan",
            "fit": "contain_pad",
            "status": "candidate",
            "protected": False,
            "asset_role": "research_reference",
        }
    except Exception as exc:
        log(f"Research image failed ({candidate.get('image_url', '')}): {exc}")
        return None
