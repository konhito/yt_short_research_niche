from unittest.mock import MagicMock

import pytest

from verticals.imgflip import create_meme, select_template


def test_select_template_matches_semantic_hint():
    templates = [
        {"id": "1", "name": "Drake Hotline Bling"},
        {"id": "2", "name": "Disaster Girl"},
    ]
    assert select_template(templates, "disaster", "game launch failed")["id"] == "2"


def test_select_template_offset_picks_alternate_matching_template():
    templates = [
        {"id": "1", "name": "Surprised Pikachu"},
        {"id": "2", "name": "Shocked Black Guy"},
        {"id": "3", "name": "Drake Hotline Bling"},
    ]

    assert select_template(templates, "surprised", "shock", offset=1)["id"] == "2"


def test_create_meme_posts_credentials_in_body_and_downloads(monkeypatch, tmp_path):
    calls = {}
    post_response = MagicMock()
    post_response.raise_for_status.return_value = None
    post_response.json.return_value = {"success": True, "data": {"url": "https://i.imgflip.com/a.jpg"}}
    image_response = MagicMock(content=b"image")
    image_response.raise_for_status.return_value = None
    monkeypatch.setattr("verticals.imgflip.requests.post", lambda url, data, timeout: calls.update(url=url, data=data) or post_response)
    monkeypatch.setattr("verticals.imgflip.requests.get", lambda url, timeout: image_response)
    output = create_meme("123", "top", "bottom", tmp_path, username="user", password="secret")
    assert calls["url"].startswith("https://")
    assert calls["data"]["password"] == "secret"
    assert output.read_bytes() == b"image"


def test_create_meme_requires_credentials(tmp_path):
    with pytest.raises(RuntimeError, match="IMGFLIP_USERNAME"):
        create_meme("123", "top", "bottom", tmp_path, username="", password="")
