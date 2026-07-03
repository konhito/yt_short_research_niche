"""Thumbnail generation - OpenAI images, meme MCP, plus Pillow text overlay."""

from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import get_gemini_key, get_openai_key, load_config
from .log import log
from .openai_images import generate_openai_image
from .retry import with_retry

THUMB_WIDTH = 1280
THUMB_HEIGHT = 720


@with_retry(max_retries=3, base_delay=2.0)
def _generate_thumb_image(prompt: str, output_path: Path, api_key: str, provider: str = "openai"):
    """Generate a 16:9 thumbnail via OpenAI or Gemini native image generation."""
    provider = (provider or "openai").lower()
    if provider == "openai":
        return generate_openai_image(
            f"Generate a bold YouTube thumbnail image: {prompt}",
            output_path,
            api_key,
            size="1024x1024",
        )

    import base64
    import requests

    url = (
        "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-2.0-flash-exp-image-generation:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": f"Generate a 16:9 landscape image: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    r = requests.post(
        url,
        json=body,
        timeout=90,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
    )
    if r.status_code != 200:
        try:
            detail = r.json().get("error", {}).get("message", r.text[:200])
        except Exception:
            detail = r.text[:200]
        hint = ""
        if r.status_code == 403:
            hint = (
                " - check that GEMINI_API_KEY is set in this environment and is "
                "an AI Studio key (https://aistudio.google.com/apikey), not a "
                "Vertex AI / service-account credential"
            )
        raise RuntimeError(f"Gemini API {r.status_code}: {detail}{hint}")

    data = r.json()
    for part in data.get("candidates", [{}])[0].get("content", {}).get("parts", []):
        if "inlineData" in part:
            img_b64 = part["inlineData"]["data"]
            output_path.write_bytes(base64.b64decode(img_b64))
            return
    raise RuntimeError("No image in Gemini response")


def _parse_hex_color(value: str, fallback=(255, 255, 255)) -> tuple[int, int, int]:
    value = str(value).lstrip("#")
    try:
        return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4)) if len(value) == 6 else fallback
    except ValueError:
        return fallback


def _overlay_title(
    image_path: Path,
    title: str,
    output_path: Path,
    profile_config: dict | None = None,
):
    """Overlay bold title text with drop shadow on the thumbnail."""
    config = profile_config or {}
    max_words = int(config.get("max_words", 0) or 0)
    if max_words:
        title = " ".join(title.split()[:max_words])
    img = Image.open(image_path).convert("RGB")
    img = img.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)
    draw = ImageDraw.Draw(img)

    font_size = 64
    font = None
    for font_name in [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/SFNSDisplay.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]:
        try:
            font = ImageFont.truetype(font_name, font_size)
            break
        except (OSError, IOError):
            continue
    if font is None:
        font = ImageFont.load_default()

    max_width = THUMB_WIDTH - 80
    lines = _wrap_text(draw, title, font, max_width)
    text_block = "\n".join(lines)

    bbox = draw.multiline_textbbox((0, 0), text_block, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (THUMB_WIDTH - text_w) // 2
    position = config.get("text_position", "center")
    if "left" in position:
        x = 60
    if "top" in position:
        y = 60
    elif "center" in position and "left" not in position:
        y = (THUMB_HEIGHT - text_h) // 2
    else:
        y = THUMB_HEIGHT - text_h - 60

    shadow_offset = 3
    draw.multiline_text(
        (x + shadow_offset, y + shadow_offset),
        text_block,
        fill=(0, 0, 0),
        font=font,
        align="center",
    )
    draw.multiline_text(
        (x, y),
        text_block,
        fill=_parse_hex_color(config.get("text_color", "#FFFFFF")),
        font=font,
        align="center",
    )

    img.save(output_path)


def _resize_thumbnail(image_path: Path, output_path: Path):
    """Resize a raw image to the standard thumbnail canvas."""
    img = Image.open(image_path).convert("RGB")
    img = img.resize((THUMB_WIDTH, THUMB_HEIGHT), Image.LANCZOS)
    img.save(output_path)


def _wrap_text(draw: ImageDraw.Draw, text: str, font, max_width: int) -> list[str]:
    """Simple word-wrap for Pillow text rendering."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), test, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _build_thumbnail_prompt(prompt: str, profile_config: dict | None = None) -> str:
    config = profile_config or {}
    details = []
    labels = (
        ("style", "Style"),
        ("text_color", "Text color"),
        ("accent_color", "Accent color"),
        ("text_position", "Text position"),
        ("font_style", "Font style"),
    )
    for key, label in labels:
        if config.get(key):
            details.append(f"{label}: {config[key]}")
    if config.get("max_words") is not None:
        details.append(f"Use maximum {config['max_words']} words of thumbnail text")
    if config.get("guidelines"):
        details.append("Rules: " + "; ".join(map(str, config["guidelines"])))
    return prompt if not details else f"{prompt}. " + ". ".join(details)


def generate_thumbnail(
    draft: dict,
    out_dir: Path,
    provider: str = "openai",
    meme_template_id: str | None = None,
    profile_config: dict | None = None,
) -> Path:
    """Generate a YouTube thumbnail with OpenAI or meme MCP."""
    prompt = _build_thumbnail_prompt(
        draft.get("thumbnail_prompt", "Cinematic YouTube thumbnail"),
        profile_config,
    )
    title = draft.get("youtube_title", draft.get("news", ""))
    job_id = draft.get("job_id", "unknown")

    raw_path = out_dir / f"thumb_raw_{job_id}.png"
    final_path = out_dir / f"thumb_{job_id}.png"

    provider = (provider or "openai").lower()
    if provider == "meme":
        from .mcp_assets import fetch_meme_image

        template_id = (
            meme_template_id
            or os.environ.get("MCP_MEME_TEMPLATE_ID")
            or load_config().get("MCP_MEME_TEMPLATE_ID")
        )
        if not template_id:
            raise RuntimeError("MCP_MEME_TEMPLATE_ID is required for meme thumbnails")

        text0 = draft.get("meme_text0") or title
        text1 = draft.get("meme_text1") or prompt
        log("Generating thumbnail via meme MCP...")
        meme_path = fetch_meme_image(str(template_id), text0, text1, out_dir)
        _resize_thumbnail(meme_path, final_path)
    else:
        api_key = get_openai_key() if provider == "openai" else get_gemini_key()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY not set - cannot generate thumbnail. "
                "Set OPENAI_API_KEY in the environment or ~/.verticals/config.json."
            )

        log(f"Generating thumbnail via {provider}...")
        _generate_thumb_image(prompt, raw_path, api_key, provider=provider)

        log("Adding title overlay...")
        _overlay_title(raw_path, title, final_path, profile_config=profile_config)

    log(f"Thumbnail saved: {final_path.name}")
    return final_path
