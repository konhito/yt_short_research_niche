"""Tests for the Flask backend."""

import json
import time

from verticals.server import create_app
from verticals.server import _draft_summary


def _wait_for_job(client, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        response = client.get(f"/api/jobs/{job_id}")
        data = response.get_json()
        job = data["job"]
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish in time")


def test_health_and_niches(tmp_path):
    app = create_app({"JOB_DIR": str(tmp_path / "jobs")})
    client = app.test_client()

    index = client.get("/")
    health = client.get("/health")
    niches = client.get("/api/niches")

    assert index.status_code == 200
    assert b"Creator cockpit" in index.data
    assert b"Generate Short" in index.data
    assert b"visualMix" in index.data
    assert b"nicheDescription" in index.data
    assert b"Research" in index.data
    assert health.status_code == 200
    assert health.get_json()["ok"] is True
    assert niches.status_code == 200
    assert niches.get_json()["ok"] is True


def test_draft_summary_exposes_visual_counts_without_credentials(tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text('{"job_id":"1","_pipeline_state":{"broll":{"artifacts":{"provider_counts":{"imgflip":4,"pexels":2}}}}}', encoding="utf-8")
    summary = _draft_summary(draft)
    assert summary["visual_summary"] == {"imgflip": 4, "pexels": 2}
    assert "password" not in str(summary).lower()


def test_draft_summary_exposes_harvest_diagnostics(tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps({
        "job_id": "1",
        "_pipeline_state": {
            "broll": {
                "artifacts": {
                    "provider_counts": {"youtube_harvest": 5, "reddit_harvest": 4, "imgflip": 7},
                    "harvest_rejected": 12,
                    "harvest_manifests": {"youtube": "yt.json", "reddit": "reddit.json"},
                }
            }
        },
    }), encoding="utf-8")

    summary = _draft_summary(draft)

    assert summary["visual_summary"]["youtube_harvest"] == 5
    assert summary["visual_summary"]["reddit_harvest"] == 4
    assert summary["harvest_summary"]["rejected"] == 12
    assert summary["harvest_summary"]["manifests"]["reddit"] == "reddit.json"


def test_run_job_completes_without_upload(tmp_path, monkeypatch):
    app = create_app({"JOB_DIR": str(tmp_path / "jobs")})
    client = app.test_client()

    draft_path = tmp_path / "draft.json"
    draft_payload = {
        "job_id": "123",
        "news": "Example topic",
        "youtube_title": "Example title",
        "youtube_description": "Example description",
        "youtube_tags": "one,two",
        "niche": "tech",
        "platform": "shorts",
    }
    draft_path.write_text(json.dumps(draft_payload), encoding="utf-8")

    video_path = tmp_path / "video.mp4"
    video_path.write_text("stub video", encoding="utf-8")

    def fake_draft(args):
        return draft_path

    def fake_produce(args):
        return video_path

    monkeypatch.setattr("verticals.server.cli.cmd_draft", fake_draft)
    monkeypatch.setattr("verticals.server.cli.cmd_produce", fake_produce)

    response = client.post(
        "/api/jobs/run",
        json={
            "topic": "Example topic",
            "niche": "tech",
            "provider": "openai",
            "voice": "edge",
            "upload": False,
        },
    )

    assert response.status_code == 202
    job_id = response.get_json()["job"]["id"]
    job = _wait_for_job(client, job_id)

    assert job["status"] == "completed"
    assert job["result"]["video_path"] == str(video_path)
    assert "youtube_url" not in job["result"]


def test_draft_job_requires_topic(tmp_path):
    app = create_app({"JOB_DIR": str(tmp_path / "jobs")})
    client = app.test_client()

    response = client.post("/api/jobs/draft", json={"niche": "tech"})

    assert response.status_code == 400
