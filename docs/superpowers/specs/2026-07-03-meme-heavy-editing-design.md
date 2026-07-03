# Meme-Heavy Editing Design

## Goal

Replace the three-image slideshow with a niche-controlled, fast-cut visual
timeline. Gaming defaults to a meme-heavy mix of free Imgflip memes, portrait
Pexels footage, and portrait OpenAI images.

## Niche Configuration

Each niche may define an `editing` block:

```yaml
editing:
  style: meme_heavy
  cut_duration_seconds: [2, 5]
  pexels_clips: [2, 4]
  meme_beats: [4, 6]
  ai_images: [1, 2]
  effects: [punch_zoom, pan, shake, hard_cut]
```

Supported styles are `cinematic`, `balanced`, and `meme_heavy`. Missing or
invalid values use conservative general defaults. Explicit API options may
override the selected niche profile.

## Draft Output

Draft generation requests a `visual_plan` in addition to legacy
`broll_prompts`. Each plan item contains:

- `type`: `pexels`, `meme`, or `ai_image`;
- `query`: footage/image search intent;
- `meme_text_top` and `meme_text_bottom` for meme items;
- `template_hint`: a short semantic hint such as `surprised`, `choice`, or
  `disaster`;
- `effect`: one of the niche-supported effects;
- `duration_seconds`: a value inside the niche cut-duration range.

The LLM receives exact source counts from the niche profile. Validation repairs
unknown types, clamps durations, enforces count ranges, and converts legacy
three-prompt drafts into an AI-image-only timeline when no visual plan exists.

## Portrait Image Generation

OpenAI b-roll requests use `1024x1536`, the supported portrait size closest to
9:16. The generated image is center-cropped to `1080x1920`; this removes much
less composition than the current square-image crop. Prompts explicitly reserve
safe areas for captions and keep the subject inside the central portrait frame.

## Free Imgflip Integration

The backend calls the official free endpoints directly:

- `GET https://api.imgflip.com/get_memes` to load popular image templates;
- `POST https://api.imgflip.com/caption_image` to create captioned images.

Credentials come from `IMGFLIP_USERNAME` and `IMGFLIP_PASSWORD` in `.env` or
the existing config loader. They are sent only as HTTPS form body parameters
and are never logged or returned by the API.

Template selection scores the normalized template name against the plan's
`template_hint`, query, and caption text. A small semantic alias table maps
common intents to popular template names. If no meaningful match exists, the
selector chooses from the most popular returned templates. Returned images are
downloaded immediately because Imgflip URLs may later be removed and are
publicly accessible.

The free API watermark is accepted. Animated GIF captioning, template search,
automeme, AI meme generation, and watermark removal are out of scope because
they require Imgflip Premium.

## Pexels Footage

The existing Pexels MCP requests portrait videos. The producer creates the
configured 2–4 clips from distinct plan queries and avoids duplicate URLs when
possible. Clips are trimmed or looped to their timeline duration and cropped to
9:16 by the existing ffmpeg path.

## Timeline And Effects

Assets are assembled in visual-plan order instead of dividing narration evenly
among three assets. Durations are normalized to exactly match voiceover length.
When the plan is too short, assets cycle with a different effect; when too long,
the final item is trimmed.

Effects are applied by asset type:

- `punch_zoom`: rapid scale-in with a short settle, suitable for memes;
- `shake`: brief positional jitter, limited to meme emphasis beats;
- `pan`: restrained Ken Burns movement for AI images;
- `hard_cut`: no transition, preserving quick pacing;
- Pexels footage keeps its native motion with crop and trim only.

No crossfades are required for the first version. Hard cuts preserve rhythm and
avoid extending segment durations unpredictably.

## Failure Handling

Each planned asset is resolved independently:

1. Try its requested provider.
2. For failed Imgflip or Pexels items, generate a portrait OpenAI image using
   the same query.
3. If OpenAI is unavailable, use a portrait fallback frame.

A provider failure cannot fail the whole production job unless no visual asset
can be produced. Logs report source counts and each fallback without exposing
credentials.

## Backend And Frontend

The backend keeps the current niche dropdown and derives editing defaults from
the selected niche. Job output includes the resolved visual-plan summary and
provider counts. No additional required frontend controls are introduced; a
future advanced panel can override editing style and counts through the API.

## Compatibility

Existing drafts with only `broll_prompts` continue through a generated legacy
timeline. Existing Pexels and OpenAI provider options remain accepted. Meme MCP
thumbnail support is independent from Imgflip timeline memes and remains
unchanged.

## Verification

Tests cover:

- gaming editing defaults and malformed-value normalization;
- exact LLM visual-plan guidance and plan validation;
- OpenAI portrait size `1024x1536` and final 9:16 dimensions;
- free Imgflip request shape, credential safety, template scoring, and download;
- configured Pexels/meme/image source counts;
- duration normalization to voiceover length;
- ffmpeg commands for punch zoom, shake, pan, and hard cuts;
- per-provider fallback behavior;
- conversion of old three-prompt drafts;
- full existing test-suite compatibility.

