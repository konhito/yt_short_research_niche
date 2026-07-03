"""Topic research aggregation across Reddit, DuckDuckGo, and pytrends."""

from __future__ import annotations

import concurrent.futures
import html
import math
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any

from urllib.parse import parse_qs, unquote, urlencode, urlparse

import feedparser
import requests

from .config import NICHE_TO_SUBREDDITS, extract_keywords
from .log import log
from .retry import with_retry


_WS_RE = re.compile(r"\s+")


@dataclass
class ResearchItem:
    source: str
    title: str
    snippet: str = ""
    url: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ResearchAggregator:
    """Gather and rank research snippets from multiple lightweight sources."""

    def __init__(
        self,
        topic: str,
        niche: str = "general",
        geo: str = "US",
        discovery: dict[str, Any] | None = None,
    ):
        self.topic = topic.strip()
        self.niche = (niche or "general").strip().lower()
        self.discovery = discovery or {}
        trends = self.discovery.get("google_trends", {}) or {}
        self.geo = (trends.get("geo") or geo or "US").strip().upper()
        self.trends_category = trends.get("category", "")
        self.query = extract_keywords(self.topic) or self.topic[:80]

    def gather(self, limit: int = 8) -> list[ResearchItem]:
        """Fetch from all sources in parallel, dedupe, and rank."""
        results: list[ResearchItem] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [
                pool.submit(self.fetch_reddit, limit),
                pool.submit(self.fetch_rss, limit),
                pool.submit(self.fetch_duckduckgo, limit),
                pool.submit(self.fetch_web_pages, min(10, max(limit, 1))),
                pool.submit(self.fetch_pytrends, limit),
            ]
            for future in concurrent.futures.as_completed(futures):
                try:
                    results.extend(future.result())
                except Exception as exc:
                    log(f"Research source failed: {exc}")

        youtube_category = (self.discovery.get("youtube_trending", {}) or {}).get("category_id")
        if youtube_category:
            log(f"YouTube trending category {youtube_category} configured (adapter unavailable - skipping)")
        return self._dedupe_and_rank(results)[:limit]

    def format_bundle(self, items: list[ResearchItem]) -> str:
        """Render research items into a compact prompt block."""
        if not items:
            return f"Topic: {self.topic}\n(No live research available - script must stay general.)"

        sections = [f"Topic: {self.topic}", f"Query: {self.query}"]
        grouped: dict[str, list[ResearchItem]] = {}
        for item in items:
            grouped.setdefault(item.source, []).append(item)

        for source in ("reddit", "web", "rss", "duckduckgo", "pytrends"):
            source_items = grouped.get(source, [])
            if not source_items:
                continue
            sections.append(f"\n[{source.upper()}]")
            for item in source_items[:4]:
                line = f"- {item.title}"
                if item.snippet:
                    line += f" :: {item.snippet}"
                if item.url:
                    line += f" ({item.url})"
                sections.append(line)
                image_url = str(item.metadata.get("image_url", ""))
                if image_url:
                    sections.append(f"  IMAGE: {image_url} | PAGE: {item.url} | TITLE: {item.title}")

        return "\n".join(sections)

    def fetch_reddit(self, limit: int = 8) -> list[ResearchItem]:
        configured = (self.discovery.get("reddit", {}) or {}).get("subreddits", [])
        subreddits = configured or NICHE_TO_SUBREDDITS.get(
            self.niche, NICHE_TO_SUBREDDITS["general"]
        )
        per_sub = max(1, limit // max(1, len(subreddits)))
        items: list[ResearchItem] = []

        for subreddit in subreddits:
            try:
                subreddit_items = self._search_subreddit(subreddit, per_sub)
                if not subreddit_items:
                    subreddit_items = self._fetch_hot_subreddit(subreddit, per_sub)
                items.extend(subreddit_items)
            except Exception as exc:
                log(f"Reddit search failed for r/{subreddit}: {exc}")
                try:
                    items.extend(self._fetch_hot_subreddit(subreddit, per_sub))
                except Exception as hot_exc:
                    log(f"Reddit fallback failed for r/{subreddit}: {hot_exc}")

        return items[:limit]

    def fetch_rss(self, limit: int = 8) -> list[ResearchItem]:
        feeds = (self.discovery.get("rss", {}) or {}).get("feeds", [])
        if not feeds:
            return []
        per_feed = max(1, limit // len(feeds))
        items: list[ResearchItem] = []
        for url in feeds:
            try:
                feed = feedparser.parse(
                    url, request_headers={"User-Agent": "verticals/3.1 research"}
                )
                if getattr(feed, "bozo", False) and not getattr(feed, "entries", None):
                    continue
                for entry in feed.entries[:per_feed]:
                    title = str(entry.get("title", "")).strip()
                    if not title:
                        continue
                    snippet = _strip_html(
                        html.unescape(str(entry.get("summary", entry.get("description", ""))))
                    ).strip()
                    items.append(ResearchItem(
                        source="rss",
                        title=title,
                        snippet=_truncate(snippet, 300),
                        url=str(entry.get("link", url)),
                        score=max(self._text_relevance(f"{title} {snippet}"), 0.1),
                        metadata={"feed": url},
                    ))
            except Exception as exc:
                log(f"RSS research failed for {url}: {exc}")
        return items[:limit]

    def fetch_duckduckgo(self, limit: int = 8) -> list[ResearchItem]:
        try:
            html = _fetch_ddg(self.query)
        except Exception as exc:
            log(f"DuckDuckGo search failed: {exc}")
            return []

        return [
            ResearchItem(
                source="duckduckgo",
                title=result["title"],
                snippet=_truncate(result["snippet"], 300),
                url=result["url"],
                score=max(0.1, 0.9 - index * 0.05),
                metadata={"query": self.query},
            )
            for index, result in enumerate(_parse_ddg_results(html, limit))
        ]

    def fetch_web_pages(self, limit: int = 10) -> list[ResearchItem]:
        try:
            search_html = _fetch_ddg(self.query)
            results = _parse_ddg_results(search_html, limit)
        except Exception as exc:
            log(f"Top website search failed: {exc}")
            return []
        items = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, max(1, len(results)))) as pool:
            futures = [pool.submit(_scrape_web_page, result, self.query) for result in results]
            for future in concurrent.futures.as_completed(futures):
                try:
                    item = future.result()
                    if item:
                        items.append(item)
                except Exception as exc:
                    log(f"Website scrape failed: {exc}")
        items.sort(key=lambda item: item.score, reverse=True)
        return items[:limit]

    def fetch_pytrends(self, limit: int = 8) -> list[ResearchItem]:
        try:
            from pytrends.request import TrendReq
        except ImportError:
            log("pytrends not installed - skipping trends research")
            return []

        try:
            pytrends = TrendReq(hl="en-US", tz=330)
            category_map = {"games": 8, "gaming": 8}
            category = category_map.get(
                str(self.trends_category).lower(), self.trends_category or 0
            )
            try:
                category = int(category)
            except (TypeError, ValueError):
                category = 0
            pytrends.build_payload(
                [self.query], timeframe="now 7-d", geo=self.geo, cat=category
            )
            related = pytrends.related_queries() or {}
        except Exception as exc:
            log(f"pytrends query failed: {exc}")
            return []

        items: list[ResearchItem] = []
        query_data = related.get(self.query) or {}
        for section_name, section_weight in (("top", 0.7), ("rising", 0.85)):
            frame = query_data.get(section_name)
            if frame is None:
                continue
            try:
                head = frame.head(limit)
            except Exception:
                continue
            for idx, row in head.iterrows():
                title = str(row.get("query", "")).strip()
                if not title:
                    continue
                value = row.get("value", "")
                items.append(
                    ResearchItem(
                        source="pytrends",
                        title=title,
                        snippet=f"{section_name}: {value}",
                        score=max(0.1, section_weight - idx * 0.04),
                        metadata={"section": section_name, "geo": self.geo},
                    )
                )

        if items:
            return items[:limit]

        try:
            trending = pytrends.trending_searches(pn=self._geo_to_pn())
        except Exception as exc:
            log(f"pytrends trending searches failed: {exc}")
            return []

        for idx, row in trending.head(limit).iterrows():
            title = str(row[0]).strip()
            if not title:
                continue
            items.append(
                ResearchItem(
                    source="pytrends",
                    title=title,
                    score=max(0.1, 1.0 - idx * 0.05),
                    metadata={"geo": self.geo, "mode": "trending_searches"},
                )
            )
        return items

    def _search_subreddit(self, subreddit: str, limit: int) -> list[ResearchItem]:
        return self._fetch_reddit_feed(subreddit, "search", limit)

    def _fetch_hot_subreddit(self, subreddit: str, limit: int) -> list[ResearchItem]:
        return self._fetch_reddit_feed(subreddit, "hot", limit)

    def _fetch_reddit_feed(self, subreddit: str, feed_type: str, limit: int) -> list[ResearchItem]:
        if feed_type == "hot":
            params = {"limit": limit + 3}
        else:
            params = {
                "q": self.query,
                "restrict_sr": 1,
                "sort": "relevance",
                "t": "month",
                "limit": limit + 3,
            }

        # Feedparser handles the response parsing and keeps us away from Reddit JSON endpoints.
        url = f"https://old.reddit.com/r/{subreddit}/{feed_type}.rss?{urlencode(params)}"
        feed = feedparser.parse(url, request_headers={"User-Agent": "verticals/3.1 research"})
        if getattr(feed, "bozo", False) and not getattr(feed, "entries", None):
            return []

        items: list[ResearchItem] = []
        for entry in feed.entries:
            title = str(entry.get("title", "")).strip()
            if not title:
                continue
            raw_summary = html.unescape(str(entry.get("summary", "")))
            text = _strip_html(raw_summary).strip()
            score = self._text_relevance(" ".join([title, text]))
            items.append(
                ResearchItem(
                    source="reddit",
                    title=title,
                    snippet=_truncate(text or title, 220),
                    url=str(entry.get("link", "")),
                    score=max(score, 0.05),
                    metadata={
                        "subreddit": subreddit,
                        "mode": feed_type,
                    },
                )
            )

        items.sort(key=lambda item: item.score, reverse=True)
        return items[:limit]

    def _dedupe_and_rank(self, items: list[ResearchItem]) -> list[ResearchItem]:
        seen: set[str] = set()
        unique: list[ResearchItem] = []
        for item in items:
            key = _normalize_key(item.title, item.url)
            if key in seen:
                continue
            seen.add(key)
            unique.append(item)
        unique.sort(key=lambda item: item.score, reverse=True)
        return unique

    def _text_relevance(self, text: str) -> float:
        tokens = {
            token
            for token in re.findall(r"[a-z0-9]+", f"{self.query} {self.topic}".lower())
            if len(token) > 2
        }
        if not tokens:
            return 0.0

        haystack = set(re.findall(r"[a-z0-9]+", text.lower()))
        overlap = len(tokens & haystack)
        return min(1.0, overlap / max(1, min(len(tokens), 6)))

    def _geo_to_pn(self) -> str:
        geo_map = {
            "IN": "india",
            "US": "united_states",
            "GB": "united_kingdom",
            "AU": "australia",
        }
        return geo_map.get(self.geo, "united_states")


@with_retry(max_retries=2, base_delay=2.0)
def _fetch_ddg(keywords: str) -> str:
    """Fetch search snippets from DuckDuckGo HTML endpoint."""
    url = "https://html.duckduckgo.com/html/"
    headers = {"User-Agent": "Mozilla/5.0 (compatible; research-bot/1.0)"}
    r = requests.post(url, data={"q": keywords}, headers=headers, timeout=10)
    r.raise_for_status()
    return r.text


def _parse_ddg_results(html_text: str, limit: int = 10) -> list[dict[str, str]]:
    results: list[dict[str, str]] = []

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.capture = ""
            self.text: list[str] = []
            self.current: dict[str, str] | None = None

        def handle_starttag(self, tag, attrs):
            values = dict(attrs)
            classes = values.get("class", "")
            if tag == "a" and "result__a" in classes:
                self.capture = "title"
                self.text = []
                self.current = {"title": "", "url": _decode_ddg_url(values.get("href", "")), "snippet": ""}
            elif tag == "a" and "result__snippet" in classes and self.current is not None:
                self.capture = "snippet"
                self.text = []

        def handle_endtag(self, tag):
            if tag != "a" or not self.capture:
                return
            value = html.unescape("".join(self.text)).strip()
            if self.current is not None:
                self.current[self.capture] = value
                if self.capture == "snippet" and self.current.get("url"):
                    results.append(self.current)
                    self.current = None
            self.capture = ""
            self.text = []

        def handle_data(self, data):
            if self.capture:
                self.text.append(data)

    Parser().feed(html_text)
    return results[:limit]


def _decode_ddg_url(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    redirect = parse_qs(parsed.query).get("uddg", [])
    return unquote(redirect[0]) if redirect else url


def _scrape_web_page(result: dict[str, str], query: str) -> ResearchItem | None:
    response = requests.get(
        result["url"],
        headers={"User-Agent": "Mozilla/5.0 (compatible; verticals-research/3.1)"},
        timeout=15,
    )
    response.raise_for_status()
    page_title = ""
    image_url = ""
    paragraphs: list[str] = []

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.in_title = False
            self.in_paragraph = False
            self.buffer: list[str] = []

        def handle_starttag(self, tag, attrs):
            nonlocal image_url
            values = dict(attrs)
            if tag == "title":
                self.in_title = True
                self.buffer = []
            elif tag == "p":
                self.in_paragraph = True
                self.buffer = []
            elif tag == "meta" and values.get("property") in {"og:image", "twitter:image"}:
                image_url = image_url or values.get("content", "")

        def handle_endtag(self, tag):
            nonlocal page_title
            if tag == "title" and self.in_title:
                page_title = html.unescape("".join(self.buffer)).strip()
                self.in_title = False
            elif tag == "p" and self.in_paragraph:
                paragraph = _WS_RE.sub(" ", html.unescape("".join(self.buffer))).strip()
                if len(paragraph) >= 40:
                    paragraphs.append(paragraph)
                self.in_paragraph = False
            self.buffer = []

        def handle_data(self, data):
            if self.in_title or self.in_paragraph:
                self.buffer.append(data)

    Parser().feed(response.text[:2_000_000])
    snippet = " ".join(paragraphs[:5]) or result.get("snippet", "")
    title = page_title or result.get("title", "")
    if not title and not snippet:
        return None
    query_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    text_tokens = set(re.findall(r"[a-z0-9]+", f"{title} {snippet}".lower()))
    relevance = min(1.0, len(query_tokens & text_tokens) / max(1, min(len(query_tokens), 6)))
    return ResearchItem(
        source="web",
        title=_truncate(title, 180),
        snippet=_truncate(snippet, 900),
        url=getattr(response, "url", result["url"]),
        score=max(0.15, relevance),
        metadata={"image_url": image_url, "query": query},
    )


def _normalize_key(title: str, url: str) -> str:
    return _WS_RE.sub(" ", f"{title} {url}".lower()).strip()[:140]


def _truncate(text: str, limit: int) -> str:
    text = text.strip()
    return text[:limit]


def _strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", " ", text)
