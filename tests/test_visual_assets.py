from pathlib import Path
import time

from verticals.visual_plan import resolve_visual_assets


def test_resolves_mixed_assets_in_plan_order(monkeypatch, tmp_path):
    monkeypatch.setattr("verticals.visual_plan.fetch_templates", lambda: [{"id": "9", "name": "Disaster Girl"}])
    monkeypatch.setattr("verticals.visual_plan.create_meme", lambda *args, **kwargs: Path(args[3]) / "meme.jpg")
    monkeypatch.setattr("verticals.visual_plan.fetch_pexels_footage", lambda query, out_dir, limit=1, **kwargs: [out_dir / "clip.mp4"])
    monkeypatch.setattr("verticals.visual_plan.generate_broll", lambda prompts, out_dir, provider="openai": [out_dir / "image.png"])
    plan = [
        {"type": "meme", "query": "failure", "template_hint": "disaster", "meme_text_top": "TOP", "meme_text_bottom": "BOTTOM", "duration_seconds": 2, "effect": "shake"},
        {"type": "pexels", "query": "gaming", "duration_seconds": 3, "effect": "hard_cut"},
        {"type": "ai_image", "query": "console", "duration_seconds": 3, "effect": "pan"},
    ]
    assets = resolve_visual_assets(plan, tmp_path)
    assert [item["source"] for item in assets] == ["imgflip", "pexels", "openai"]
    assert all("path" in item for item in assets)


def test_resolve_visual_assets_uses_pexels_search_query(monkeypatch, tmp_path):
    queries = []
    monkeypatch.setattr("verticals.visual_plan.fetch_local_footage", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "verticals.visual_plan.fetch_pexels_footage",
        lambda query, out_dir, limit=1, **kwargs: queries.append(query) or [out_dir / "clip.mp4"],
    )

    assets = resolve_visual_assets([
        {
            "type": "pexels",
            "query": "gta 6 leaks",
            "topic_query": "gta 6 leaks",
            "search_query": "angry gamer reaction",
            "duration_seconds": 3,
        }
    ], tmp_path)

    assert queries == ["angry gamer reaction"]
    assert assets[0]["query"] == "gta 6 leaks"
    assert assets[0]["topic_query"] == "gta 6 leaks"


def test_resolve_visual_assets_falls_back_to_pixabay_when_pexels_fails(monkeypatch, tmp_path):
    monkeypatch.setattr("verticals.visual_plan.fetch_local_footage", lambda *args, **kwargs: [])
    monkeypatch.setattr(
        "verticals.visual_plan.fetch_pexels_footage",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("pexels bad")),
    )
    monkeypatch.setattr(
        "verticals.visual_plan.fetch_pixabay_footage",
        lambda query, out_dir, limit=1, **kwargs: [out_dir / "pixabay.mp4"],
    )

    assets = resolve_visual_assets([
        {"type": "pexels", "query": "gta 6 leaks", "search_query": "angry gamer reaction"}
    ], tmp_path)

    assert assets[0]["source"] == "pixabay"
    assert Path(assets[0]["path"]).name == "pixabay.mp4"


def test_resolve_visual_assets_runs_independent_assets_in_parallel(monkeypatch, tmp_path):
    monkeypatch.setattr("verticals.visual_plan.generate_broll", lambda prompts, out_dir, provider="openai": (time.sleep(0.12), [out_dir / f"{prompts[0]}.png"])[1])

    started = time.perf_counter()
    assets = resolve_visual_assets([
        {"type": "ai_image", "query": "one"},
        {"type": "ai_image", "query": "two"},
        {"type": "ai_image", "query": "three"},
    ], tmp_path)
    elapsed = time.perf_counter() - started

    assert [Path(asset["path"]).name for asset in assets] == ["one.png", "two.png", "three.png"]
    assert elapsed < 0.3
