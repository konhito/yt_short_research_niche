"""Cross-job media usage history used to prevent repetitive edits."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .config import SKILL_DIR

DEFAULT_HISTORY_PATH = SKILL_DIR / "asset_history.json"


def asset_key(asset: dict) -> str:
    """Return a stable key before or after an asset has been downloaded."""
    media_hash = str(asset.get("media_hash", "")).strip()
    if media_hash:
        return f"hash:{media_hash}"
    source = str(asset.get("source", "unknown")).strip().lower()
    source_id = str(asset.get("source_id") or asset.get("id") or "").strip()
    if source_id:
        return f"{source}:id:{source_id.lower()}"
    url = _normalize_url(str(asset.get("url") or asset.get("media_url") or ""))
    if url:
        return f"{source}:url:{url}"
    path = str(asset.get("path", "")).replace("\\", "/").lower().strip()
    return f"{source}:path:{path}" if path else ""


def asset_keys(asset: dict) -> list[str]:
    """Return every stable identity available for cross-stage matching."""
    source = str(asset.get("source", "unknown")).strip().lower()
    keys = []
    media_hash = str(asset.get("media_hash", "")).strip()
    source_id = str(asset.get("source_id") or asset.get("id") or "").strip()
    url = _normalize_url(str(asset.get("url") or asset.get("media_url") or ""))
    if media_hash:
        keys.append(f"hash:{media_hash}")
    if source_id:
        keys.append(f"{source}:id:{source_id.lower()}")
    if url:
        keys.append(f"{source}:url:{url}")
    primary = asset_key(asset)
    if primary and primary not in keys:
        keys.append(primary)
    return keys


def filter_fresh_candidates(
    candidates: list[dict],
    *,
    max_items: int,
    recent_jobs: int = 10,
    history_path: Path | None = None,
) -> tuple[list[dict], list[dict]]:
    """Prefer never-used candidates and reject assets from recent edits."""
    history = _load(history_path)
    entries = history.get("assets", {})
    recent = set(history.get("job_order", [])[-max(0, recent_jobs):])
    fresh: list[dict] = []
    reused: list[dict] = []
    rejected: list[dict] = []
    for candidate in candidates:
        entry = next((entries[key] for key in asset_keys(candidate) if key in entries), {})
        jobs = set(entry.get("jobs", []))
        decorated = {
            **candidate,
            "previous_use_count": int(entry.get("used_count", 0)),
            "last_used_job": entry.get("last_job", ""),
        }
        if jobs & recent:
            rejected.append({**decorated, "reuse_reason": "used in a recent job"})
            reused.append(decorated)
        else:
            fresh.append(decorated)
    selected = fresh[:max_items]
    if len(selected) < max_items:
        # Exhausted pools still work, but choose the least-used/oldest clips first.
        reused.sort(key=lambda item: (item["previous_use_count"], item.get("last_used_job", "")))
        selected.extend(reused[: max_items - len(selected)])
    return selected, rejected


def mark_used_assets(
    assets: list[dict],
    job_id: str,
    *,
    history_path: Path | None = None,
) -> None:
    """Record only media that survived into the final editor timeline."""
    if not job_id:
        return
    path = Path(history_path or DEFAULT_HISTORY_PATH)
    history = _load(path)
    entries = history.setdefault("assets", {})
    job_order = history.setdefault("job_order", [])
    if job_id not in job_order:
        job_order.append(job_id)
    seen = set()
    now = datetime.now(timezone.utc).isoformat()
    for asset in assets:
        keys = asset_keys(asset)
        if not keys or any(key in seen for key in keys):
            continue
        seen.update(keys)
        entry = next((entries[key] for key in keys if key in entries), None) or {
            "source": asset.get("source", ""),
            "title": asset.get("title", ""),
            "url": asset.get("url", ""),
            "used_count": 0,
            "jobs": [],
        }
        if job_id not in entry["jobs"]:
            entry["jobs"].append(job_id)
            entry["used_count"] = int(entry.get("used_count", 0)) + 1
        entry["last_job"] = job_id
        entry["last_used_at"] = now
        for key in keys:
            entries[key] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(history, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def _load(path: Path | None) -> dict:
    target = Path(path or DEFAULT_HISTORY_PATH)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {"assets": {}, "job_order": []}
    except (OSError, ValueError):
        return {"assets": {}, "job_order": []}


def _normalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url.strip())
    query = urlencode([
        (key, value) for key, value in parse_qsl(parts.query)
        if key.lower() not in {"feature", "si", "utm_source", "utm_medium", "utm_campaign"}
    ])
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), query, ""))
