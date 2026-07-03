from io import BytesIO
from unittest.mock import MagicMock

from PIL import Image

from verticals.research_assets import discover_and_download_research_images, download_research_images


def _image_bytes(width=1200, height=800):
    buffer = BytesIO()
    Image.new("RGB", (width, height), "blue").save(buffer, format="JPEG")
    return buffer.getvalue()


def test_download_research_images_preserves_source_metadata(monkeypatch, tmp_path):
    response = MagicMock(content=_image_bytes())
    response.raise_for_status.return_value = None
    monkeypatch.setattr("verticals.research_assets.requests.get", lambda *args, **kwargs: response)

    assets = download_research_images([{
        "image_url": "https://img.example/gta-map.jpg",
        "source_url": "https://news.example/gta-map",
        "title": "GTA 6 map comparison",
    }], tmp_path)

    assert len(assets) == 1
    assert assets[0]["source"] == "web_research"
    assert assets[0]["type"] == "research_image"
    assert assets[0]["url"] == "https://news.example/gta-map"
    assert assets[0]["path"].endswith("research_00.jpg")


def test_download_research_images_rejects_tiny_images(monkeypatch, tmp_path):
    response = MagicMock(content=_image_bytes(100, 100))
    response.raise_for_status.return_value = None
    monkeypatch.setattr("verticals.research_assets.requests.get", lambda *args, **kwargs: response)

    assets = download_research_images([{
        "image_url": "https://img.example/icon.jpg",
        "source_url": "https://example.com",
        "title": "Tiny icon",
    }], tmp_path)

    assert assets == []


def test_discover_and_download_combines_existing_and_search_tag_images(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(
        "verticals.research_assets.discover_search_tag_images",
        lambda tags, niche, limit: [{"image_url": "https://img.test/new.jpg", "search_tag": tags[0]}],
    )
    monkeypatch.setattr(
        "verticals.research_assets.download_research_images",
        lambda candidates, out_dir, limit: captured.extend(candidates) or [{"path": str(out_dir / "image.jpg")}],
    )

    result = discover_and_download_research_images(
        ["specific visual tag"],
        [{"image_url": "https://img.test/existing.jpg"}],
        tmp_path,
        limit=4,
        niche="gaming",
    )

    assert len(captured) == 2
    assert result
