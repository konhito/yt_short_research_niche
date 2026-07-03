# Visual Clip Review Design

## Goal

Make the editor brain inspect representative frames from every harvested video,
discard irrelevant or unusable clips, and select useful source ranges before it
builds the final edit timeline. Add Vimeo as another independently harvested
video source.

## Scope

This feature reviews downloaded video candidates from YouTube, Reddit, Vimeo,
Pexels, and future providers that use the normalized candidate schema. Rejected
files remain on disk for debugging but are excluded from timeline planning.
Static images and memes keep their current path and are not part of this first
visual clip-review pass.

## Pipeline

1. Build script beats and provider-specific search queries from the completed
   draft rather than directly from raw user input.
2. Harvest YouTube, Reddit, and Vimeo concurrently. Existing Pexels and other
   visual generation remains independent and may run concurrently as today.
3. Download each candidate into its provider directory and normalize its
   metadata.
4. Sample six frames at 8%, 24%, 40%, 56%, 72%, and 88% of clip duration. Save
   the individual JPEGs and one labelled contact sheet beside the clip.
5. Review contact sheets in bounded OpenAI vision batches. Each request includes
   the script beats, timed transcript segments, candidate metadata, and images.
6. Persist the returned decision and useful ranges to a review manifest. Keep
   rejected media files, but pass only approved assets to the timeline editor.
7. Give the final editor brain approved assets, their visual descriptions,
   matched beat IDs, and allowed source ranges. Timeline validation clamps every
   selected offset to one approved range.

## Vimeo Harvesting

`verticals/vimeo_harvest.py` owns Vimeo discovery and download. When
`VIMEO_ACCESS_TOKEN` is configured, it searches public videos through the
official Vimeo API using generated script-beat queries and short-duration
filters. It normalizes API results, scores metadata, and downloads selected
public videos with the existing yt-dlp runtime.

When no token is configured, the harvester requests the public Vimeo search URL,
extracts canonical public clip URLs, and asks yt-dlp for metadata before scoring
and downloading. This fallback is best-effort because page markup may change.
Vimeo errors are returned as rejected records and never fail other harvesters or
the production job.

Configuration keys:

- `VIMEO_ACCESS_TOKEN`: optional official API token.
- `editing.vimeo_clips`: minimum and maximum Vimeo cuts, default `[0, 4]`.
- `editing.vimeo_harvest_results`: metadata candidates per run, default `20`.

## Frame Sampling

`verticals/clip_frames.py` exposes a provider-neutral function that accepts a
normalized video candidate and output directory. It probes duration, extracts
six frames through the configured ffmpeg executable, and creates a labelled
contact sheet. Frame records contain `path`, `timestamp_seconds`, and
`position_ratio`. Failures annotate only that candidate and leave it available
for deterministic metadata scoring.

The existing three-frame contact sheet remains compatible, but newly reviewed
clips use the six-frame format. Sampling does not modify or delete source media.

## Vision Review Contract

`verticals/clip_review.py` sends batches small enough to avoid image and token
limits. The OpenAI model receives the story title, script beats, timed SRT
segments, search query, source metadata, clip duration, and contact sheet for
each candidate. It must return JSON only:

```json
{
  "clips": [
    {
      "asset_id": "candidate-id",
      "decision": "keep",
      "relevance_score": 0.91,
      "quality_score": 0.82,
      "reason": "Shows Claude interface during the matching script beat",
      "visual_description": "Claude chat UI and Anthropic branding",
      "matched_beat_ids": ["beat_002"],
      "useful_ranges": [
        {"start": 4.2, "end": 8.8, "reason": "Relevant interface close-up"}
      ],
      "warnings": []
    }
  ]
}
```

Allowed decisions are `keep` and `discard`. Scores are clamped to `[0, 1]`.
Useful ranges must be ordered, non-overlapping, at least 0.75 seconds long, and
inside the source duration. Invalid ranges are dropped. A kept clip with no
valid range receives one conservative range around its highest-scoring sampled
frame. Review warnings use stable values such as `watermark`,
`unrelated_captions`, `talking_head`, `duplicate`, `low_resolution`, and
`wrong_topic`.

The default keep threshold is `0.58`. A `wrong_topic` warning forces discard.
Protected assets are not force-kept because visual relevance is the purpose of
this review; generated images and memes are outside this review stage.

## Failure Handling

If OpenAI vision is unavailable, malformed, or times out, candidates fall back
to existing metadata and quality scoring. A candidate is kept only when it
already passes quality checks and its normalized relevance score meets the
threshold. The fallback adds `review_mode: metadata_fallback` so the outcome is
visible in manifests and logs.

One failed batch does not discard all clips. It falls back only for candidates
in that batch. Raw model output is never trusted directly; every decision is
validated against known candidate IDs and source durations.

## Editor Integration

The review result enriches each approved candidate with:

- `review_decision`
- `review_reason`
- `vision_relevance_score`
- `visual_description`
- `matched_beat_ids`
- `approved_source_ranges`
- `review_warnings`

The final editor prompt receives these fields and must choose
`source_start_seconds` and segment duration inside an approved range.
`validate_editor_timeline` enforces the same boundary. If the model selects an
invalid offset, validation moves it to the nearest valid range instead of using
an arbitrary beginning of the clip.

Discarded records are stored in `clip_review_manifest.json` with their paths and
reasons. Console output reports reviewed, kept, discarded, and fallback counts
by provider.

## Testing

Tests cover deterministic six-frame timestamp calculation, contact-sheet
metadata, JSON validation, invalid range removal, wrong-topic rejection,
per-batch fallback, preservation of rejected files, editor range clamping,
Vimeo API and HTML fallback discovery, cross-provider parallel execution, and
failure isolation. Network, OpenAI, yt-dlp, and ffmpeg boundaries are stubbed;
normalization and validation use real functions.

The complete suite and Python compile check must pass before completion.
