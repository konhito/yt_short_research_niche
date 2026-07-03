"""Research orchestration built on top of the ResearchAggregator."""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed

from .log import log
from .niche import get_discovery_config, load_niche
from .research_aggregator import ResearchAggregator


def research_topic(news: str, niche: str = "general", limit: int = 10) -> str:
    """Aggregate Reddit, DuckDuckGo, and pytrends research into a prompt block."""
    discovery = get_discovery_config(load_niche(niche))
    log("Researching topic via Reddit + RSS + DuckDuckGo + pytrends...")
    aggregator = ResearchAggregator(news, niche=niche, discovery=discovery)
    items = aggregator.gather(limit=limit)
    if items:
        log(f"Research bundle assembled from {len(items)} items.")
    bundle = aggregator.format_bundle(items)
    log(f"Research bundle:\n{bundle}")
    return bundle


def extract_research_images(bundle: str) -> list[dict[str, str]]:
    """Extract structured image candidates embedded in a research bundle."""
    images = []
    seen = set()
    pattern = re.compile(r"^\s*IMAGE:\s*(\S+)\s*\|\s*PAGE:\s*(\S+)\s*\|\s*TITLE:\s*(.+)$", re.M)
    for image_url, source_url, title in pattern.findall(bundle):
        if image_url in seen:
            continue
        seen.add(image_url)
        images.append({
            "image_url": image_url,
            "source_url": source_url,
            "title": title.strip(),
        })
    return images


def discover_search_tag_images(
    search_tags: list[str], niche: str = "general", limit: int = 6
) -> list[dict[str, str]]:
    """Use each AI tag for DDG/top-page image discovery in parallel."""
    tags = [str(tag).strip() for tag in search_tags if str(tag).strip()]
    if not tags or limit <= 0:
        return []
    discovery = get_discovery_config(load_niche(niche))
    per_tag = max(1, (limit + len(tags) - 1) // len(tags))

    def search(tag: str):
        aggregator = ResearchAggregator(tag, niche=niche, discovery=discovery)
        return tag, aggregator.fetch_web_pages(per_tag)

    images = []
    seen = set()
    with ThreadPoolExecutor(max_workers=min(5, len(tags))) as executor:
        futures = [executor.submit(search, tag) for tag in tags]
        for future in as_completed(futures):
            try:
                tag, items = future.result()
            except Exception as exc:
                log(f"Search-tag image discovery failed: {exc}")
                continue
            for item in items:
                image_url = str(item.metadata.get("image_url", "")).strip()
                if not image_url or image_url in seen:
                    continue
                seen.add(image_url)
                images.append({
                    "image_url": image_url,
                    "source_url": item.url,
                    "title": item.title,
                    "search_tag": tag,
                })
    log(f"Search-tag discovery found {len(images[:limit])} web image candidate(s)")
    return images[:limit]
