from pathlib import Path

from verticals.vimeo_harvest import discover_vimeo_api, extract_vimeo_urls, harvest_vimeo_clips


class _Response:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


def test_discover_vimeo_api_normalizes_public_results(monkeypatch):
    def fake_get(url, **kwargs):
        assert url == "https://api.vimeo.com/videos"
        assert kwargs["headers"]["Authorization"] == "Bearer token"
        return _Response({"data": [{
            "uri": "/videos/123", "link": "https://vimeo.com/123",
            "name": "Anthropic Claude demo", "duration": 28,
            "user": {"name": "Studio"},
        }]})

    monkeypatch.setattr("verticals.vimeo_harvest.requests.get", fake_get)
    results = discover_vimeo_api("Anthropic Claude", "token", limit=5)

    assert results[0]["source_id"] == "123"
    assert results[0]["title"] == "Anthropic Claude demo"
    assert results[0]["url"] == "https://vimeo.com/123"


def test_extract_vimeo_urls_deduplicates_canonical_clips():
    html = '''
      <a href="/123456789">one</a>
      <a href="https://vimeo.com/123456789">duplicate</a>
      <a href="/987654321">two</a>
      <a href="/search">ignore</a>
    '''

    assert extract_vimeo_urls(html) == [
        "https://vimeo.com/123456789",
        "https://vimeo.com/987654321",
    ]


def test_harvest_vimeo_downloads_and_normalizes_candidate(monkeypatch, tmp_path):
    monkeypatch.setattr("verticals.vimeo_harvest.get_vimeo_key", lambda: "token")
    monkeypatch.setattr("verticals.vimeo_harvest.build_vimeo_queries", lambda *_args, **_kwargs: ["Anthropic Claude"])
    monkeypatch.setattr("verticals.vimeo_harvest.discover_vimeo_api", lambda *_args, **_kwargs: [{
        "source": "vimeo_harvest", "source_id": "123", "id": "123",
        "title": "Anthropic Claude product demo", "url": "https://vimeo.com/123",
        "duration": 20, "uploader": "Studio", "query": "Anthropic Claude",
        "relevance_score": 20,
    }])
    monkeypatch.setattr("verticals.vimeo_harvest._yt_dlp_base_cmd", lambda: ["yt-dlp"])

    def fake_run(command, **_kwargs):
        assert _kwargs["encoding"] == "utf-8"
        assert _kwargs["errors"] == "replace"
        output_index = command.index("-o") + 1
        output = Path(command[output_index].replace("%(id)s", "123").replace("%(ext)s", "mp4"))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"video")
        return type("Result", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr("verticals.vimeo_harvest.subprocess.run", fake_run)
    monkeypatch.setattr("verticals.vimeo_harvest.enrich_candidate", lambda asset: {**asset, "actual_duration": 20.0})
    result = harvest_vimeo_clips(
        {"script": "Anthropic Claude product demo", "search_tags": ["Anthropic Claude"]},
        tmp_path,
        max_results=5,
        max_downloads=1,
    )

    assert result["assets"][0]["source"] == "vimeo_harvest"
    assert result["assets"][0]["status"] == "candidate"
    assert Path(result["assets"][0]["path"]).exists()
