"""Flask backend for Verticals pipeline jobs.

This is a small backend layer around the existing CLI pipeline. It accepts
JSON requests, runs jobs in background threads, and persists job state to disk
so status can be polled after restarts.
"""

from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from flask import Flask, jsonify, render_template_string, request

from . import __main__ as cli
from .config import SKILL_DIR
from .niche import load_niche, list_niches


JOB_DIR = SKILL_DIR / "jobs"

INDEX_HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Verticals Backend</title>
  <style>
    :root {
      color-scheme: dark;
      --bg: #09111f;
      --panel: rgba(15, 23, 42, 0.82);
      --panel-2: rgba(30, 41, 59, 0.9);
      --line: rgba(148, 163, 184, 0.2);
      --text: #e2e8f0;
      --muted: #94a3b8;
      --accent: #22c55e;
      --accent-2: #38bdf8;
      --danger: #fb7185;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      background:
        radial-gradient(circle at top left, rgba(34, 197, 94, 0.25), transparent 30%),
        radial-gradient(circle at top right, rgba(56, 189, 248, 0.2), transparent 28%),
        linear-gradient(180deg, #030712, var(--bg) 40%, #020617);
      color: var(--text);
    }
    .wrap {
      max-width: 1040px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }
    .hero {
      display: grid;
      gap: 18px;
      grid-template-columns: 1.4fr 1fr;
      align-items: start;
      margin-bottom: 24px;
    }
    .card {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 20px;
      box-shadow: 0 20px 60px rgba(0, 0, 0, 0.28);
      backdrop-filter: blur(12px);
    }
    .brand {
      padding: 26px;
    }
    .brand h1 {
      margin: 0 0 10px;
      font-size: clamp(2rem, 4vw, 4rem);
      line-height: 0.95;
      letter-spacing: -0.05em;
    }
    .brand p {
      margin: 0;
      color: var(--muted);
      max-width: 60ch;
      line-height: 1.6;
    }
    .status {
      padding: 20px;
      display: grid;
      gap: 12px;
    }
    .pill {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 12px;
      border-radius: 999px;
      background: rgba(34, 197, 94, 0.12);
      color: #bbf7d0;
      border: 1px solid rgba(34, 197, 94, 0.25);
      width: fit-content;
    }
    .grid {
      display: grid;
      gap: 16px;
      grid-template-columns: 1.1fr 0.9fr;
    }
    .panel {
      padding: 20px;
    }
    label {
      display: block;
      margin: 0 0 8px;
      font-weight: 600;
      color: #dbeafe;
    }
    input, select, button, textarea {
      width: 100%;
      border-radius: 14px;
      border: 1px solid var(--line);
      background: rgba(15, 23, 42, 0.9);
      color: var(--text);
      padding: 14px 16px;
      font: inherit;
    }
    textarea {
      min-height: 110px;
      resize: vertical;
    }
    .row {
      display: grid;
      gap: 14px;
    }
    .two {
      display: grid;
      gap: 14px;
      grid-template-columns: 1fr 1fr;
    }
    button {
      cursor: pointer;
      font-weight: 700;
      background: linear-gradient(135deg, var(--accent), #16a34a);
      border: none;
      color: #052e16;
      transition: transform 0.15s ease, filter 0.15s ease;
    }
    button:hover { transform: translateY(-1px); filter: brightness(1.03); }
    button:disabled { opacity: 0.55; cursor: not-allowed; transform: none; }
    .secondary {
      background: linear-gradient(135deg, #38bdf8, #0ea5e9);
      color: #082f49;
    }
    .muted { color: var(--muted); }
    .list {
      display: grid;
      gap: 10px;
      margin-top: 16px;
    }
    .job {
      padding: 14px;
      border-radius: 14px;
      background: var(--panel-2);
      border: 1px solid var(--line);
    }
    .job strong { display: block; margin-bottom: 6px; }
    .error { color: #fecaca; }
    .success { color: #bbf7d0; }
    code {
      background: rgba(15, 23, 42, 0.85);
      padding: 2px 6px;
      border-radius: 6px;
    }
    .kicker {
      margin-bottom: 14px;
      color: #fbbf24;
      font-weight: 800;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-size: 0.78rem;
    }
    .hero-copy {
      display: grid;
      gap: 18px;
    }
    .hero-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 20px;
    }
    .chip {
      display: inline-flex;
      align-items: center;
      border: 1px solid rgba(251, 191, 36, 0.28);
      background: rgba(251, 191, 36, 0.09);
      color: #fde68a;
      border-radius: 999px;
      padding: 8px 11px;
      font-size: 0.82rem;
      font-weight: 700;
    }
    .composer-head {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 18px;
    }
    .composer-head h2, .panel-title {
      margin: 0;
      font-size: 1.2rem;
      letter-spacing: -0.03em;
    }
    .topic-box {
      min-height: 150px;
      font-size: 1.05rem;
      background:
        linear-gradient(180deg, rgba(2, 6, 23, 0.96), rgba(15, 23, 42, 0.94)),
        radial-gradient(circle at 20% 20%, rgba(56, 189, 248, 0.18), transparent 35%);
      border-color: rgba(56, 189, 248, 0.24);
    }
    .form-hint {
      margin-top: 7px;
      color: #7dd3fc;
      font-size: 0.83rem;
    }
    .stage-grid {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 16px;
    }
    .stage {
      border: 1px solid rgba(148, 163, 184, 0.18);
      background: rgba(2, 6, 23, 0.45);
      border-radius: 14px;
      padding: 11px;
    }
    .stage span {
      display: block;
      color: #f8fafc;
      font-weight: 800;
      margin-bottom: 3px;
    }
    .stage small { color: var(--muted); }
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 10px;
      margin-top: 16px;
    }
    .metric {
      border-radius: 16px;
      border: 1px solid rgba(56, 189, 248, 0.18);
      background: rgba(14, 165, 233, 0.08);
      padding: 12px;
    }
    .metric strong {
      display: block;
      font-size: 1.35rem;
      line-height: 1;
      color: #f8fafc;
    }
    .metric span { color: var(--muted); font-size: 0.78rem; }
    .job {
      position: relative;
      overflow: hidden;
    }
    .job::before {
      content: "";
      position: absolute;
      inset: 0 auto 0 0;
      width: 4px;
      background: linear-gradient(180deg, #f59e0b, #22c55e, #38bdf8);
    }
    .job-top {
      display: flex;
      gap: 10px;
      justify-content: space-between;
      align-items: start;
    }
    .badges {
      display: flex;
      flex-wrap: wrap;
      gap: 7px;
      margin-top: 10px;
    }
    .badge {
      border: 1px solid rgba(148, 163, 184, 0.2);
      background: rgba(15, 23, 42, 0.75);
      color: #cbd5e1;
      padding: 5px 8px;
      border-radius: 999px;
      font-size: 0.76rem;
      font-weight: 700;
    }
    .status-dot {
      width: 9px;
      height: 9px;
      border-radius: 999px;
      background: #fbbf24;
      box-shadow: 0 0 18px rgba(251, 191, 36, 0.55);
      display: inline-block;
    }
    .status-dot.completed { background: #22c55e; }
    .status-dot.failed { background: #fb7185; }
    .message-card {
      margin-top: 14px;
      border-radius: 16px;
      border: 1px solid rgba(148, 163, 184, 0.16);
      background: rgba(2, 6, 23, 0.45);
      padding: 13px 14px;
    }
    @media (max-width: 900px) {
      .hero, .grid, .two, .stage-grid, .metric-grid { grid-template-columns: 1fr; }
      .composer-head, .job-top { display: grid; }
    }
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <section class="card brand">
        <div class="kicker">Creator cockpit</div>
        <h1>Ship sharper Shorts without babysitting the terminal.</h1>
        <p>
          Draft scripts, pull research, mix meme-heavy visuals, generate voice,
          captions, music, and assemble a portrait video from one focused console.
        </p>
        <div class="hero-actions">
          <span class="chip">Gaming defaults on</span>
          <span class="chip">4-8 YouTube clips</span>
          <span class="chip">4-8 Reddit clips</span>
          <span class="chip">6-10 Imgflip memes</span>
        </div>
      </section>
      <section class="card status">
        <div class="panel-title">Live system</div>
        <div id="serverStatus" class="pill">Checking...</div>
        <div class="muted">API base: <code>POST /api/jobs/run</code></div>
        <div class="muted">Current job: <code id="currentJob">none</code></div>
        <div class="stage-grid">
          <div class="stage"><span>Research</span><small>Reddit, RSS, trends</small></div>
          <div class="stage"><span>Script</span><small>OpenAI or selected LLM</small></div>
          <div class="stage"><span>Memes</span><small>Free Imgflip beats</small></div>
          <div class="stage"><span>Harvest</span><small>YouTube + Reddit video</small></div>
          <div class="stage"><span>Voice</span><small>Edge TTS ready</small></div>
          <div class="stage"><span>Assemble</span><small>Fast-cut timeline</small></div>
        </div>
      </section>
    </div>

    <div class="grid">
      <section class="card panel">
        <div class="composer-head">
          <div>
            <div class="muted">New short</div>
            <h2>Topic composer</h2>
          </div>
          <span class="chip">Upload off by default</span>
        </div>
        <form id="jobForm" class="row">
          <div>
            <label for="topic">Topic</label>
            <textarea id="topic" class="topic-box" name="topic" placeholder="GTA 6 leak backlash, Nintendo lawsuit drama, AI NPCs changing open-world games..." required></textarea>
            <div class="form-hint">Write it like a creator brief. The pipeline will research and structure the short.</div>
          </div>
          <div class="two">
            <div>
              <label for="niche">Niche</label>
              <select id="niche" name="niche"></select>
              <div id="nicheDescription" class="form-hint">Gaming meme-heavy mode is selected by default.</div>
            </div>
            <div>
              <label for="provider">LLM Provider</label>
              <select id="provider" name="provider">
                <option value="">Auto</option>
                <option value="openai">OpenAI</option>
                <option value="claude">Claude</option>
                <option value="gemini">Gemini</option>
                <option value="ollama">Ollama</option>
              </select>
            </div>
          </div>
          <div class="two">
            <div>
              <label for="voice">Voice</label>
              <select id="voice" name="voice">
                <option value="edge">Edge TTS</option>
                <option value="elevenlabs">ElevenLabs</option>
                <option value="minimax">MiniMax</option>
                <option value="60db">60db</option>
              </select>
            </div>
            <div>
              <label for="upload">Upload</label>
              <select id="upload" name="upload">
                <option value="false">No upload</option>
                <option value="true">Upload to YouTube</option>
              </select>
            </div>
          </div>
          <div class="two">
            <button id="runBtn" type="submit">Generate Short</button>
            <button id="refreshBtn" type="button" class="secondary">Refresh jobs</button>
          </div>
        </form>
        <div id="message" class="message-card muted">Ready. Pick a topic and launch a clean backend job.</div>
      </section>

      <section class="card panel">
        <div class="composer-head">
          <div>
            <div class="muted">Queue</div>
            <h2>Recent jobs</h2>
          </div>
          <span class="chip" id="visualMix">Visual mix: gaming</span>
        </div>
        <div class="metric-grid">
          <div class="metric"><strong>6+</strong><span>meme beats</span></div>
          <div class="metric"><strong>8+</strong><span>harvested clips</span></div>
          <div class="metric"><strong>9:16</strong><span>portrait output</span></div>
        </div>
        <div id="jobs" class="list"></div>
      </section>
    </div>
  </div>

  <script>
    const nicheSelect = document.getElementById('niche');
    const nicheDescription = document.getElementById('nicheDescription');
    const statusEl = document.getElementById('serverStatus');
    const jobsEl = document.getElementById('jobs');
    const messageEl = document.getElementById('message');
    const jobForm = document.getElementById('jobForm');
    const runBtn = document.getElementById('runBtn');
    const currentJobEl = document.getElementById('currentJob');

    async function loadNiches() {
      const res = await fetch('/api/niches');
      const data = await res.json();
      nicheSelect.innerHTML = data.niches.map(n => (
        `<option value="${n.name}">${n.display_name || n.name}</option>`
      )).join('');
      nicheSelect.value = data.niches.some(n => n.name === 'gaming') ? 'gaming' : (data.niches[0]?.name || 'general');
      updateNicheDescription(data.niches);
      nicheSelect.addEventListener('change', () => updateNicheDescription(data.niches));
    }

    function updateNicheDescription(niches) {
      const selected = niches.find(n => n.name === nicheSelect.value);
      nicheDescription.textContent = selected?.description || 'Choose a niche to tune script, visuals, voice, and editing.';
    }

    async function loadHealth() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        statusEl.textContent = data.ok ? 'Online' : 'Offline';
        statusEl.style.background = data.ok ? 'rgba(34,197,94,0.12)' : 'rgba(251,113,133,0.12)';
      } catch (err) {
        statusEl.textContent = 'Offline';
        statusEl.style.background = 'rgba(251,113,133,0.12)';
      }
    }

    function renderJobs(jobs) {
      if (!jobs.length) {
        jobsEl.innerHTML = '<div class="muted">No jobs yet.</div>';
        return;
      }
      jobsEl.innerHTML = jobs.slice(0, 8).map(job => {
        const result = job.result || {};
        const title = result.youtube_title || result.news || job.payload?.topic || 'Untitled';
        const extra = job.status === 'failed'
          ? `<div class="error">${job.error?.message || 'Failed'}</div>`
          : job.status === 'completed'
            ? `<div class="success">${result.video_path ? 'Video ready' : 'Completed'}</div>`
            : `<div class="muted">${job.status}</div>`;
        return `
          <div class="job">
            <strong>${title}</strong>
            <div class="muted"><code>${job.id}</code> · ${job.kind} · ${job.status}</div>
            ${extra}
          </div>
        `;
      }).join('');
    }

    function renderJobsV2(jobs) {
      if (!jobs.length) {
        jobsEl.innerHTML = '<div class="job"><strong>No jobs yet</strong><div class="muted">Generated shorts will appear here with status and visual mix.</div></div>';
        return;
      }
      jobsEl.innerHTML = jobs.slice(0, 8).map(job => {
        const result = job.result || {};
        const title = result.youtube_title || result.news || job.payload?.topic || 'Untitled';
        const visual = result.visual_summary || {};
        const badges = [
          result.niche || job.payload?.niche,
          visual.imgflip ? `${visual.imgflip} memes` : null,
          visual.youtube_harvest ? `${visual.youtube_harvest} YouTube` : null,
          visual.reddit_harvest ? `${visual.reddit_harvest} Reddit` : null,
          visual.pexels ? `${visual.pexels} Pexels` : null,
          visual.openai || visual.openai_fallback ? `${(visual.openai || 0) + (visual.openai_fallback || 0)} AI frames` : null,
          result.lang ? result.lang.toUpperCase() : null,
        ].filter(Boolean).map(value => `<span class="badge">${value}</span>`).join('');
        const extra = job.status === 'failed'
          ? `<div class="error">${job.error?.message || 'Failed'}</div>`
          : job.status === 'completed'
            ? `<div class="success">${result.video_path ? 'Video ready' : 'Completed'}</div>`
            : `<div class="muted">${job.status}</div>`;
        return `
          <div class="job">
            <div class="job-top">
              <strong>${title}</strong>
              <span class="status-dot ${job.status}"></span>
            </div>
            <div class="muted"><code>${job.id}</code> - ${job.kind} - ${job.status}</div>
            <div class="badges">${badges}</div>
            ${extra}
          </div>
        `;
      }).join('');
    }

    async function loadJobs() {
      const res = await fetch('/api/jobs');
      const data = await res.json();
      renderJobsV2(data.jobs || []);
    }

    async function pollJob(jobId) {
      currentJobEl.textContent = jobId;
      const tick = async () => {
        const res = await fetch(`/api/jobs/${jobId}`);
        const data = await res.json();
        const job = data.job;
        messageEl.textContent = job.status === 'running'
          ? 'Running stages: research, script, memes, Pexels, voice, captions, assemble...'
          : `Job ${job.status}: ${job.kind}`;
        if (job.status === 'completed') {
          const result = job.result || {};
          messageEl.textContent = result.video_path
            ? `Done. Video ready at ${result.video_path}`
            : 'Done.';
          await loadJobs();
          runBtn.disabled = false;
          return;
        }
        if (job.status === 'failed') {
          messageEl.textContent = job.error?.message || 'Job failed.';
          messageEl.className = 'error';
          await loadJobs();
          runBtn.disabled = false;
          return;
        }
        setTimeout(tick, 2000);
      };
      setTimeout(tick, 1500);
    }

    jobForm.addEventListener('submit', async (event) => {
      event.preventDefault();
      runBtn.disabled = true;
      messageEl.className = 'muted';
      messageEl.textContent = 'Submitting job...';
      const body = {
        topic: document.getElementById('topic').value.trim(),
        niche: nicheSelect.value,
        provider: document.getElementById('provider').value || undefined,
        voice: document.getElementById('voice').value,
        upload: document.getElementById('upload').value === 'true',
      };
      const res = await fetch('/api/jobs/run', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json();
      if (!res.ok) {
        messageEl.textContent = data.error || 'Job submission failed.';
        messageEl.className = 'error';
        runBtn.disabled = false;
        return;
      }
      messageEl.textContent = 'Job queued.';
      currentJobEl.textContent = data.job.id;
      await loadJobs();
      await pollJob(data.job.id);
    });

    document.getElementById('refreshBtn').addEventListener('click', loadJobs);

    (async () => {
      await Promise.all([loadNiches(), loadHealth(), loadJobs()]);
    })();
  </script>
</body>
</html>
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _job_file(base_dir: Path, job_id: str) -> Path:
    return base_dir / f"{job_id}.json"


class JobStore:
    """Persist job metadata to JSON files under ~/.verticals/jobs."""

    def __init__(self, base_dir: Path = JOB_DIR):
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def create(self, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
        job = {
            "id": uuid.uuid4().hex,
            "kind": kind,
            "status": "queued",
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "payload": payload,
            "result": {},
            "warnings": [],
            "error": None,
        }
        self.save(job)
        return job

    def save(self, job: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            job["updated_at"] = _utc_now()
            _job_file(self.base_dir, job["id"]).write_text(
                json.dumps(job, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        return job

    def load(self, job_id: str) -> dict[str, Any] | None:
        path = _job_file(self.base_dir, job_id)
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return None

    def list(self) -> list[dict[str, Any]]:
        jobs: list[dict[str, Any]] = []
        for path in sorted(self.base_dir.glob("*.json"), reverse=True):
            try:
                jobs.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                continue
        jobs.sort(key=lambda j: j.get("created_at", ""), reverse=True)
        return jobs

    def update(self, job_id: str, **changes: Any) -> dict[str, Any]:
        job = self.load(job_id)
        if job is None:
            raise KeyError(job_id)
        job.update(changes)
        return self.save(job)


def _draft_summary(draft_path: Path) -> dict[str, Any]:
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
    except Exception:
        return {"draft_path": str(draft_path)}

    summary = {
        "draft_path": str(draft_path),
        "job_id": draft.get("job_id"),
        "news": draft.get("news"),
        "youtube_title": draft.get("youtube_title"),
        "youtube_description": draft.get("youtube_description"),
        "youtube_tags": draft.get("youtube_tags"),
        "niche": draft.get("niche"),
        "platform": draft.get("platform"),
    }
    provider_counts = (
        draft.get("_pipeline_state", {})
        .get("broll", {})
        .get("artifacts", {})
        .get("provider_counts")
    )
    if isinstance(provider_counts, dict):
        summary["visual_summary"] = provider_counts
    broll_artifacts = (
        draft.get("_pipeline_state", {})
        .get("broll", {})
        .get("artifacts", {})
    )
    summary["harvest_summary"] = {
        "rejected": int(broll_artifacts.get("harvest_rejected", 0) or 0),
        "manifests": broll_artifacts.get("harvest_manifests", {}) or {},
    }
    return summary


def _run_draft_job(store: JobStore, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store.update(job_id, status="running")
    args = SimpleNamespace(
        news=payload["topic"],
        context=payload.get("context", ""),
        niche=payload.get("niche", "general"),
        platform=payload.get("platform", "shorts"),
        provider=payload.get("provider"),
    )
    draft_path = cli.cmd_draft(args)
    summary = _draft_summary(Path(draft_path))
    store.update(job_id, status="completed", result=summary)
    return summary


def _ensure_draft_path(job_id: str, payload: dict[str, Any]) -> Path:
    if payload.get("draft_path"):
        return Path(payload["draft_path"])

    if payload.get("draft"):
        draft_obj = payload["draft"]
        if isinstance(draft_obj, dict):
            draft_path = JOB_DIR / f"{job_id}-draft.json"
            draft_path.write_text(json.dumps(draft_obj, indent=2, ensure_ascii=False), encoding="utf-8")
            return draft_path

    raise ValueError("Provide either draft_path or draft JSON object.")


def _run_produce_job(store: JobStore, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store.update(job_id, status="running")
    draft_path = _ensure_draft_path(job_id, payload)
    args = SimpleNamespace(
        draft=str(draft_path),
        lang=payload.get("lang", "en"),
        script=payload.get("script"),
        force=bool(payload.get("force", False)),
        voice=payload.get("voice"),
    )
    video_path = cli.cmd_produce(args)
    result = {
        **_draft_summary(draft_path),
        "video_path": str(video_path),
        "lang": args.lang,
    }
    store.update(job_id, status="completed", result=result)
    return result


def _run_pipeline_job(store: JobStore, job_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    store.update(job_id, status="running")
    warnings: list[str] = []

    draft_args = SimpleNamespace(
        news=payload["topic"],
        context=payload.get("context", ""),
        niche=payload.get("niche", "general"),
        platform=payload.get("platform", "shorts"),
        provider=payload.get("provider"),
    )
    draft_path = cli.cmd_draft(draft_args)

    result: dict[str, Any] = _draft_summary(Path(draft_path))
    result["warnings"] = warnings

    if payload.get("dry_run"):
        store.update(job_id, status="completed", result=result, warnings=warnings)
        return result

    produce_args = SimpleNamespace(
        draft=str(draft_path),
        lang=payload.get("lang", "en"),
        script=payload.get("script"),
        force=bool(payload.get("force", False)),
        voice=payload.get("voice"),
    )
    video_path = cli.cmd_produce(produce_args)
    result["video_path"] = str(video_path)
    result["lang"] = produce_args.lang

    if payload.get("upload", False):
        upload_args = SimpleNamespace(
            draft=str(draft_path),
            lang=produce_args.lang,
            force=False,
        )
        try:
            url = cli.cmd_upload(upload_args)
            result["youtube_url"] = url
        except FileNotFoundError as exc:
            warnings.append(str(exc))
            result["youtube_url"] = None
    store.update(job_id, status="completed", result=result, warnings=warnings)
    return result


def _handle_job(store: JobStore, job_id: str, kind: str, payload: dict[str, Any]):
    try:
        if kind == "draft":
            _run_draft_job(store, job_id, payload)
        elif kind == "produce":
            _run_produce_job(store, job_id, payload)
        elif kind == "run":
            _run_pipeline_job(store, job_id, payload)
        else:
            raise ValueError(f"Unknown job kind: {kind}")
    except Exception as exc:
        store.update(
            job_id,
            status="failed",
            error={
                "message": str(exc),
                "traceback": traceback.format_exc(),
            },
        )


def _json_error(message: str, status_code: int = 400):
    return jsonify({"ok": False, "error": message}), status_code


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.update(
        JOB_DIR=str(JOB_DIR),
        PROJECT_NAME="verticals",
        VERSION="3.1.0",
    )
    if test_config:
        app.config.update(test_config)

    store = JobStore(Path(app.config["JOB_DIR"]))

    def _spawn(kind: str, payload: dict[str, Any]):
        if kind in {"draft", "produce", "run"}:
            if kind == "draft" and "topic" not in payload:
                raise ValueError("topic is required")
            if kind in {"produce", "run"}:
                if not payload.get("draft_path") and not payload.get("draft"):
                    if kind == "produce":
                        raise ValueError("draft_path or draft JSON is required")
                    if "topic" not in payload:
                        raise ValueError("topic is required")
        job = store.create(kind, payload)
        thread = threading.Thread(
            target=_handle_job,
            args=(store, job["id"], kind, payload),
            daemon=True,
        )
        thread.start()
        return job

    @app.get("/")
    def index():
        return render_template_string(INDEX_HTML)

    @app.get("/health")
    def health():
        return jsonify({
            "ok": True,
            "service": "verticals-backend",
            "version": app.config["VERSION"],
        })

    @app.get("/api/niches")
    def api_niches():
        items = []
        for name in list_niches():
            profile = load_niche(name)
            items.append({
                "name": name,
                "display_name": profile.get("display_name", name),
                "description": profile.get("description", ""),
            })
        return jsonify({"ok": True, "niches": items})

    @app.get("/api/jobs")
    def api_jobs():
        return jsonify({"ok": True, "jobs": store.list()})

    @app.get("/api/jobs/<job_id>")
    def api_job(job_id: str):
        job = store.load(job_id)
        if not job:
            return _json_error("job not found", 404)
        return jsonify({"ok": True, "job": job})

    @app.post("/api/jobs/draft")
    def api_create_draft():
        payload = request.get_json(silent=True) or {}
        if not payload.get("topic"):
            return _json_error("topic is required")
        try:
            job = _spawn("draft", payload)
        except ValueError as exc:
            return _json_error(str(exc))
        return jsonify({"ok": True, "job": job}), 202

    @app.post("/api/jobs/produce")
    def api_create_produce():
        payload = request.get_json(silent=True) or {}
        try:
            job = _spawn("produce", payload)
        except ValueError as exc:
            return _json_error(str(exc))
        return jsonify({"ok": True, "job": job}), 202

    @app.post("/api/jobs/run")
    def api_create_run():
        payload = request.get_json(silent=True) or {}
        if not payload.get("topic"):
            return _json_error("topic is required")
        try:
            job = _spawn("run", payload)
        except ValueError as exc:
            return _json_error(str(exc))
        return jsonify({"ok": True, "job": job}), 202

    return app


def main():
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST", "127.0.0.1")
    debug = os.environ.get("FLASK_DEBUG", "").lower() in {"1", "true", "yes", "on"}
    app = create_app()
    app.run(host=host, port=port, debug=debug)


if __name__ == "__main__":
    main()
