"""Free Imgflip API client for static timeline memes."""

from __future__ import annotations

import re
from pathlib import Path

import requests

from .config import _get_key


ALIASES = {
    "disaster": {"disaster", "girl"},
    "choice": {"drake", "buttons", "choice"},
    "surprised": {"surprised", "pikachu", "shock", "shocked"},
    "success": {"success", "kid", "win"},
}


def get_imgflip_credentials() -> tuple[str, str]:
    return _get_key("IMGFLIP_USERNAME"), _get_key("IMGFLIP_PASSWORD")


def fetch_templates() -> list[dict]:
    response = requests.get("https://api.imgflip.com/get_memes", timeout=20)
    response.raise_for_status()
    data = response.json()
    if not data.get("success"):
        raise RuntimeError("Imgflip template request failed")
    return data.get("data", {}).get("memes", [])


def select_template(templates: list[dict], hint: str = "", text: str = "", offset: int = 0) -> dict:
    if not templates:
        raise RuntimeError("Imgflip returned no meme templates")
    terms = set(re.findall(r"[a-z0-9]+", f"{hint} {text}".lower()))
    for key, aliases in ALIASES.items():
        if key in terms:
            terms.update(aliases)
    scored = []
    for index, template in enumerate(templates):
        name_terms = set(re.findall(r"[a-z0-9]+", str(template.get("name", "")).lower()))
        scored.append((len(terms & name_terms), -index, template))
    ranked = sorted(scored, key=lambda row: (row[0], row[1]), reverse=True)
    matching = [row for row in ranked if row[0] > 0] or ranked
    return matching[offset % len(matching)][2]


def create_meme(
    template_id: str,
    text_top: str,
    text_bottom: str,
    out_dir: Path,
    *,
    username: str | None = None,
    password: str | None = None,
) -> Path:
    username, password = (username, password) if username is not None else get_imgflip_credentials()
    if not username or not password:
        raise RuntimeError("IMGFLIP_USERNAME and IMGFLIP_PASSWORD are required for free meme generation")
    response = requests.post(
        "https://api.imgflip.com/caption_image",
        data={"template_id": template_id, "username": username, "password": password, "text0": text_top, "text1": text_bottom},
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(f"Imgflip caption failed: {payload.get('error_message', 'unknown error')}")
    image = requests.get(payload["data"]["url"], timeout=30)
    image.raise_for_status()
    out_path = out_dir / f"imgflip_{template_id}_{len(list(out_dir.glob('imgflip_*')))}.jpg"
    out_path.write_bytes(image.content)
    return out_path
