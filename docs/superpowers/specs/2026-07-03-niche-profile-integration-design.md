# Niche Profile Integration Design

## Goal

Make every supported field in `niches/*.yaml` affect the corresponding pipeline
stage. Niche values are defaults. Explicit CLI, API, and frontend selections
override those defaults.

## Configuration Boundary

`verticals/niche.py` remains the only module that interprets raw niche YAML.
It exposes normalized, stage-specific configuration dictionaries for script,
research, visuals, voice, captions, music, and thumbnails. Pipeline stages do
not inspect arbitrary YAML fields directly.

Unknown fields remain harmless and missing fields receive the existing general
defaults. Provider aliases are normalized at this boundary; notably, `edge`
and `edge_tts` resolve to the same voice configuration.

## Data Flow

1. The frontend sends the selected niche plus any explicit provider choices.
2. Draft generation loads the profile and applies script, visual, thumbnail,
   and music guidance to the LLM prompt.
3. Research receives normalized discovery configuration from the profile.
4. The saved draft records the niche name and generated stage plans.
5. Production reloads that profile and applies voice, caption, music, visual,
   and thumbnail defaults.
6. Explicit request values override profile defaults at their respective stage.

## Research

The aggregator accepts normalized discovery configuration and uses:

- `reddit.subreddits` for Reddit search and fallback feeds.
- `rss.feeds` as additional niche-specific evidence sources.
- `google_trends.category` and `google_trends.geo` for Trends queries.
- `youtube_trending.category_id` when a YouTube discovery source is available.

The current hardcoded subreddit map remains only as a fallback for profiles
without discovery configuration. A failed source logs its error and does not
prevent other sources from producing a research bundle. The console output
identifies which configured sources contributed results.

## Script And Visuals

The drafting prompt continues to include tone, pacing, perspective, word count,
hooks, structure, CTA options, and forbidden phrases. Visual guidance expands
to include the configured color palette along with style, mood, preferred
subjects, avoided subjects, and prompt suffix.

The suffix is appended exactly once to generated b-roll prompts. Both OpenAI
image generation and Pexels search consume the resulting prompts.

## Voice

Provider names are normalized before looking up suggested voices. A frontend
selection of `edge` therefore resolves `voice.suggested_voices.edge_tts`.
Provider-specific IDs and settings are passed to the TTS implementation.

Descriptive pace, energy, and style remain generation guidance where the TTS
provider cannot directly express them. Supported numeric provider settings are
passed through unchanged.

## Captions

Caption generation accepts and applies:

- highlight and normal text colors;
- font family, size, and weight;
- lower-third or centered position;
- configured background treatment;
- words per group.

ASS styles translate these normalized values into alignment, margins, border
style, outline, shadow, and color fields. SRT remains plain text and timing only.
Unsupported values fall back to the current safe defaults.

## Music

The music plan uses niche mood, energy, tags, and any LLM-produced plan. Local
tracks are ranked by case-insensitive tag matches in their filenames. The best
matching group is selected randomly to retain variation; if no filenames match,
selection falls back to all tracks.

Speech and gap ducking volumes continue to come from the niche profile. If no
music files exist, the plan is retained and the pipeline proceeds without music.

## Thumbnail

Draft generation includes style, text color, accent color, text position,
maximum word count, font style, and guidelines in thumbnail guidance. The
normalized thumbnail configuration is also passed to image generation so its
final prompt preserves these constraints even when a stored draft prompt is
minimal.

## Overrides

Precedence is:

1. Explicit CLI/API/frontend value.
2. Selected niche profile value.
3. General pipeline default.

An explicit provider changes the provider but still uses that provider's voice
settings from the selected niche unless a specific voice ID is also supplied.

## Compatibility And Errors

Existing draft files that contain only a niche name continue to work. Missing,
malformed, or partial profile sections use defaults. External research failures
are isolated per source. Invalid presentation values are normalized instead of
being inserted directly into ffmpeg filters.

## Verification

Tests will prove:

- provider aliases select the gaming Edge voice;
- gaming discovery settings reach Reddit, RSS, Trends, and YouTube adapters;
- visual palette and all thumbnail fields appear in generated guidance;
- every caption style field affects generated ASS output;
- music filenames are ranked by niche tags and ducking values reach assembly;
- explicit request values override niche defaults;
- partial profiles preserve existing defaults and existing tests remain green.

