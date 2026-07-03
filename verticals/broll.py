"""OpenAI b-roll generation + Ken Burns animation."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from .config import VIDEO_WIDTH, VIDEO_HEIGHT, get_gemini_key, get_openai_key, run_cmd
from .log import log
from .openai_images import generate_openai_image
from .retry import with_retry


def _fallback_frame(i: int, out_dir: Path) -> Path:
    """Solid colour fallback frame if image generation fails."""
    colors = [(20, 20, 60), (40, 10, 40), (10, 30, 50)]
    img = Image.new("RGB", (VIDEO_WIDTH, VIDEO_HEIGHT), colors[i % len(colors)])
    path = out_dir / f"broll_{i}.png"
    img.save(path)
    return path


def _resize_to_portrait(image_path: Path, output_path: Path):
    """Resize/crop an image to 9:16 portrait."""
    img = Image.open(image_path).convert("RGB")
    target_w, target_h = VIDEO_WIDTH, VIDEO_HEIGHT
    orig_w, orig_h = img.size
    scale = max(target_w / orig_w, target_h / orig_h)
    new_w, new_h = int(orig_w * scale), int(orig_h * scale)
    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    img = img.crop((left, top, left + target_w, top + target_h))
    img.save(output_path)


def generate_broll(prompts: list, out_dir: Path, provider: str = "openai") -> list[Path]:
    """Generate 3 b-roll frames via OpenAI, with fallback frames."""
    provider = (provider or "openai").lower()
    api_key = get_openai_key() if provider == "openai" else get_gemini_key()
    if not api_key:
        log(
            "OPENAI_API_KEY not set - using solid-color fallback frames."
            if provider == "openai"
            else "GEMINI_API_KEY not set - using solid-color fallback frames."
        )
        return [_fallback_frame(i, out_dir) for i in range(min(3, max(len(prompts), 1)))]

    frames = []
    for i, prompt in enumerate(prompts[:3]):
        out_path = out_dir / f"broll_{i}.png"
        log(f"Generating b-roll frame {i+1}/3 via {provider}...")

        try:
            if provider == "openai":
                generate_openai_image(
                    "Generate a cinematic vertical portrait b-roll frame. Keep the main "
                    f"subject inside the central 9:16 safe area for later cropping: {prompt}",
                    out_path,
                    api_key,
                    size="1024x1536",
                )
            else:
                _generate_image_gemini(prompt, out_path, api_key)

            _resize_to_portrait(out_path, out_path)
            frames.append(out_path)
        except Exception as exc:
            log(f"Frame {i+1} failed: {exc} - using fallback")
            frames.append(_fallback_frame(i, out_dir))

    return frames


@with_retry(max_retries=3, base_delay=2.0)
def _generate_image_gemini(prompt: str, output_path: Path, api_key: str):
    """Legacy Gemini fallback for b-roll generation."""
    import base64
    import requests

    url = (
        "https://generativelanguage.googleapis.com/v1beta"
        "/models/gemini-2.0-flash-exp-image-generation:generateContent"
    )
    body = {
        "contents": [{"parts": [{"text": f"Generate an image: {prompt}"}]}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }
    r = requests.post(
        url, json=body, timeout=90,
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


def animate_frame(img_path: Path, out_path: Path, duration: float, effect: str = "zoom_in"):
    """Ken Burns animation on a single frame."""
    fps = 30
    frames = int(duration * fps)
    w, h = VIDEO_WIDTH, VIDEO_HEIGHT

    if effect == "punch_zoom":
        vf = (
            f"scale={int(w * 1.18)}:{int(h * 1.18)},"
            f"zoompan=z='if(lt(on,8),1+0.025*on,1.2-0.08*(on-8)/max(1,{frames}-8))'"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps}"
        )
    elif effect == "shake":
        vf = (
            f"scale={int(w * 1.08)}:{int(h * 1.08)},"
            f"crop={w}:{h}:x='(iw-{w})/2+8*sin(n*2.1)':y='(ih-{h})/2+6*sin(n*2.7)'"
        )
    elif effect in ("pan", "pan_right"):
        vf = (
            f"scale={int(w * 1.15)}:{int(h * 1.15)},"
            f"zoompan=z=1.15:x='0.15*iw*on/{frames}':y='ih*0.075'"
            f":d={frames}:s={w}x{h}:fps={fps}"
        )
    elif effect == "hard_cut":
        vf = f"scale={w}:{h},fps={fps}"
    elif effect == "zoom_in":
        vf = (
            f"scale={int(w * 1.12)}:{int(h * 1.12)},"
            f"zoompan=z='1.12-0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={w}x{h}:fps={fps}"
        )
    else:  # zoom_out
        vf = (
            f"scale={int(w * 1.12)}:{int(h * 1.12)},"
            f"zoompan=z='1.0+0.12*on/{frames}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":d={frames}:s={w}x{h}:fps={fps}"
        )

    run_cmd([
        "ffmpeg", "-loop", "1", "-i", str(img_path),
        "-vf", vf, "-t", str(duration), "-r", str(fps),
        "-pix_fmt", "yuv420p", str(out_path), "-y", "-loglevel", "quiet",
    ])


def animate_meme_frame(
    img_path: Path,
    out_path: Path,
    duration: float,
    effect: str = "punch_zoom",
    fill_color: str = "#0D0D0D",
):
    """Render a meme without forcing it into a 9:16 crop.

    Memes are usually landscape/square with text baked into the image. Cropping
    them destroys the joke, so we fit to the video width and pad vertically.
    """
    fps = 30
    color = str(fill_color or "#0D0D0D").replace("'", "")
    vf = (
        f"scale={VIDEO_WIDTH}:-2:force_original_aspect_ratio=decrease,"
        f"pad={VIDEO_WIDTH}:{VIDEO_HEIGHT}:(ow-iw)/2:(oh-ih)/2:color={color},"
        f"fps={fps}"
    )
    run_cmd([
        "ffmpeg", "-loop", "1", "-i", str(img_path),
        "-vf", vf, "-t", str(duration), "-r", str(fps),
        "-pix_fmt", "yuv420p", str(out_path), "-y", "-loglevel", "quiet",
    ])
