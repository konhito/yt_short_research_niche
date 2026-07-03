"""Tests for the research aggregator."""

from verticals.research import discover_search_tag_images, extract_research_images, research_topic
from verticals.research_aggregator import ResearchAggregator, ResearchItem, _parse_ddg_results, _scrape_web_page


def test_format_bundle_groups_sources():
    agg = ResearchAggregator("gta 6 leaks", niche="gaming")
    items = [
        ResearchItem(source="reddit", title="Reddit post", snippet="players are debating this", url="https://reddit.com/r/test", score=0.9),
        ResearchItem(source="duckduckgo", title="DDG result", snippet="major outlets covered it", score=0.8),
        ResearchItem(source="pytrends", title="GTA 6", snippet="rising: 95", score=0.7),
    ]

    text = agg.format_bundle(items)

    assert "Topic: gta 6 leaks" in text
    assert "[REDDIT]" in text
    assert "[DUCKDUCKGO]" in text
    assert "[PYTRENDS]" in text


def test_research_topic_uses_aggregator(monkeypatch):
    captured = {}

    class FakeAgg:
        def __init__(self, topic, niche="general", geo="US", discovery=None):
            captured["topic"] = topic
            captured["niche"] = niche
            captured["discovery"] = discovery

        def gather(self, limit=8):
            return [ResearchItem(source="reddit", title="Example", snippet="snippet", score=1.0)]

        def format_bundle(self, items):
            return f"Topic: {captured['topic']} | niche={captured['niche']} | items={len(items)}"

    monkeypatch.setattr("verticals.research.ResearchAggregator", FakeAgg)

    result = research_topic("AI automation", niche="tech")

    assert "Topic: AI automation" in result
    assert "niche=tech" in result
    assert "items=1" in result
    assert captured["discovery"] is not None


def test_reddit_uses_profile_subreddits(monkeypatch):
    agg = ResearchAggregator(
        "gta 6", niche="gaming",
        discovery={"reddit": {"subreddits": ["Games", "esports"]}},
    )
    seen = []
    monkeypatch.setattr(agg, "_search_subreddit", lambda subreddit, limit: seen.append(subreddit) or [])
    monkeypatch.setattr(agg, "_fetch_hot_subreddit", lambda subreddit, limit: [])
    agg.fetch_reddit(limit=4)
    assert seen == ["Games", "esports"]


def test_rss_uses_profile_feeds(monkeypatch):
    agg = ResearchAggregator(
        "gta 6", niche="gaming",
        discovery={"rss": {"feeds": ["https://example.test/gaming.xml"]}},
    )
    monkeypatch.setattr(
        "verticals.research_aggregator.feedparser.parse",
        lambda url, **kwargs: type("Feed", (), {"entries": [{"title": "GTA update", "summary": "New details", "link": url}], "bozo": False})(),
    )
    items = agg.fetch_rss(limit=2)
    assert items[0].source == "rss"
    assert items[0].url == "https://example.test/gaming.xml"


def test_reddit_fallback_uses_hot_posts(monkeypatch):
    agg = ResearchAggregator("gta 6 leaks", niche="gaming")
    calls = {"hot": 0}

    def fake_search(subreddit, limit):
        raise RuntimeError("403 blocked")

    def fake_hot(subreddit, limit):
        calls["hot"] += 1
        return [
            ResearchItem(
                source="reddit",
                title=f"{subreddit} hot post",
                snippet="fallback content",
                url=f"https://reddit.com/r/{subreddit}/hot",
                score=0.9,
            )
        ]

    monkeypatch.setattr(agg, "_search_subreddit", fake_search)
    monkeypatch.setattr(agg, "_fetch_hot_subreddit", fake_hot)

    items = agg.fetch_reddit(limit=4)

    assert items
    assert calls["hot"] >= 1
    assert all(item.source == "reddit" for item in items)


def test_parse_ddg_results_extracts_real_urls():
    html = '''
    <a class="result__a" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fgta-map">GTA Map</a>
    <a class="result__snippet">A detailed GTA 6 map comparison.</a>
    '''

    results = _parse_ddg_results(html, limit=10)

    assert results[0]["title"] == "GTA Map"
    assert results[0]["url"] == "https://example.com/gta-map"
    assert "map comparison" in results[0]["snippet"]


def test_scrape_web_page_extracts_text_and_og_image(monkeypatch):
    response = type("Response", (), {
        "text": '''<html><head><title>GTA 6 Map</title><meta property="og:image" content="https://img.example/map.jpg"></head><body><p>The map includes Vice City and surrounding areas.</p></body></html>''',
        "url": "https://example.com/article",
        "raise_for_status": lambda self: None,
    })()
    monkeypatch.setattr("verticals.research_aggregator.requests.get", lambda *args, **kwargs: response)

    item = _scrape_web_page({"title": "Result", "url": "https://example.com/article", "snippet": "snippet"}, "GTA 6 map")

    assert item.source == "web"
    assert item.metadata["image_url"] == "https://img.example/map.jpg"
    assert "Vice City" in item.snippet


def test_format_bundle_includes_research_image_marker():
    agg = ResearchAggregator("GTA 6 map", niche="gaming")
    text = agg.format_bundle([
        ResearchItem(
            source="web",
            title="GTA Map",
            snippet="Map comparison",
            url="https://example.com/map",
            score=1,
            metadata={"image_url": "https://img.example/map.jpg"},
        )
    ])

    assert "[WEB]" in text
    assert "IMAGE: https://img.example/map.jpg" in text
    assert extract_research_images(text)[0]["image_url"] == "https://img.example/map.jpg"


def test_discover_search_tag_images_searches_each_ai_tag(monkeypatch):
    searched = []

    class FakeAgg:
        def __init__(self, topic, **kwargs):
            self.topic = topic

        def fetch_web_pages(self, limit):
            searched.append(self.topic)
            return [ResearchItem(
                source="web",
                title=f"Image for {self.topic}",
                url=f"https://page.test/{self.topic}",
                metadata={"image_url": f"https://img.test/{self.topic}.jpg"},
            )]

    monkeypatch.setattr("verticals.research.ResearchAggregator", FakeAgg)
    tags = [f"exact tag {index}" for index in range(5)]

    images = discover_search_tag_images(tags, niche="gaming", limit=5)

    assert sorted(searched) == sorted(tags)
    assert len(images) == 5
    assert all(image["search_tag"] in tags for image in images)
