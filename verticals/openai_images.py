"""OpenAI image generation helpers."""

from __future__ import annotations

import base64
from pathlib import Path

import requests

from .log import log
from .retry import with_retry


@with_retry(max_retries=3, base_delay=2.0)
def generate_openai_image(
    prompt: str,
    output_path: Path,
    api_key: str,
    *,
    size: str = "1024x1024",
    quality: str = "high",
    background: str = "auto",
) -> Path:
    """Generate an image via OpenAI's image API and write it to disk."""
    url = "https://api.openai.com/v1/images/generations"
    body = {
        "model": "gpt-image-1",
        "prompt": prompt,
        "size": size,
        "quality": quality,
        "background": background,
    }
    r = requests.post(
        url,
        json=body,
        timeout=120,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            detail = r.text[:200]
        raise RuntimeError(f"OpenAI image API {r.status_code}: {detail}")

    data = r.json()
    item = (data.get("data") or [{}])[0]
    if item.get("b64_json"):
        output_path.write_bytes(base64.b64decode(item["b64_json"]))
        log(f"OpenAI image saved: {output_path.name}")
        return output_path
    if item.get("url"):
        image = requests.get(item["url"], timeout=120)
        image.raise_for_status()
        output_path.write_bytes(image.content)
        log(f"OpenAI image saved: {output_path.name}")
        return output_path
    raise RuntimeError("No image in OpenAI response")
