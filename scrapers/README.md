# badge.video scrapers

Run commands from this folder:

```powershell
cd C:\Users\ryan\Documents\GitHub\badge.video\scrapers
```

## 1. Find New Videos

Uses the official YouTube API and writes/updates video JSON files.

```powershell
uv run pipeline.py videos
```

## 2. Generate Transcripts

Recommended batch command:

```powershell
uv run pipeline.py transcripts --provider local-asr --delay-seconds 5 --verbose
```

This downloads audio with `yt-dlp` and transcribes locally with `faster-whisper`.

Default model:

```text
distil-large-v3 on CUDA, int8_float16
```

Transcript runs skip existing transcripts by default, so you can stop and restart safely.

To regenerate existing transcripts:

```powershell
uv run pipeline.py transcripts --provider local-asr --overwrite --verbose
```

Single-video test:

```powershell
uv run pipeline.py transcripts --provider local-asr --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json" --verbose
```

## 3. Classify Videos

Uses `LLM_BACKEND` from `../.env`.

```powershell
uv run pipeline.py classify --no-overwrite
```

Default classifier context sends scraped video metadata plus compact timestamped transcript text. It does not also send the full transcript text or JSON segment objects, so DeepSeek is not charged for duplicate transcript copies.

Classifier runs skip videos without an available transcript by default, so this can run while transcripts are still being generated.

You can set the default in `../.env`:

```env
LLM_TRANSCRIPT_CONTEXT=timestamped_text
```

Cheaper mode without timestamps:

```powershell
uv run pipeline.py classify --no-overwrite --transcript-context text
```

Timestamped JSON segment mode, useful for debugging but more expensive:

```powershell
uv run pipeline.py classify --no-overwrite --transcript-context segments
```

Debug/metadata-only mode:

```powershell
uv run pipeline.py classify --no-overwrite --transcript-context none --include-untranscribed
```

Single-video classifier test:

```powershell
uv run pipeline.py classify --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json"
```

Classification rebuilds `..\database\metadata_atlas.json` by default. That file contains global frontend filter lists like states, counties, cities, location names, ZIP codes when explicitly known, agencies, crime categories, incident types, tags, and content warnings.

To rebuild only the atlas:

```powershell
uv run pipeline.py atlas
```

## Full Pipeline

Recommended:

```powershell
uv run pipeline.py videos
uv run pipeline.py transcripts --provider local-asr --delay-seconds 5 --verbose
uv run pipeline.py classify --no-overwrite
uv run pipeline.py atlas
```

## Build Website Data

Bake compact JSON for the static frontend. This rebuilds the atlas first and only includes classified videos by default.

```powershell
uv run pipeline.py site-data
```

Local website test:

```powershell
cd ..\frontend
python -m http.server 5173
```

Then open:

```text
http://localhost:5173
```

The browser reads `frontend\public\data\videos.index.json`, not the full transcript-heavy video JSON files.

One command version:

```powershell
uv run pipeline.py pipeline --provider local-asr --delay-seconds 5 --verbose
```

## YouTube Transcript Routes

There are three transcript providers:

```text
direct           YouTube timedtext/watch-page captions
ytdlp-subtitles  YouTube captions through yt-dlp
local-asr        Download audio and transcribe locally
```

The YouTube caption routes can work, but they are currently unreliable for this project because YouTube often returns `429 Too Many Requests`. If you want predictable batch runs, use:

```powershell
uv run pipeline.py transcripts --provider local-asr --delay-seconds 5 --verbose
```

If you want to try captions first and fall back to local ASR:

```powershell
uv run pipeline.py transcripts --provider auto --allow-local-asr --delay-seconds 5 --verbose
```

## Review Behavior

- New videos start with `"human_reviewed": false`.
- Re-scraping preserves transcript, classification, and manual fields.
- Re-scraping clears `human_reviewed` only when core YouTube metadata changes.
- Re-running classification clears `human_reviewed`.
- Transcript generation does not clear `human_reviewed`.

## Environment

`../.env`:

```env
YOUTUBE_API_KEY=...
LLM_BACKEND=dry_run
LLM_MODEL=deepseek-chat
LLM_TRANSCRIPT_CONTEXT=timestamped_text
DEEPSEEK_API_KEY=...
OLLAMA_URL=http://localhost:11434/api/chat
```

Use `LLM_BACKEND=dry_run` until you are ready to call DeepSeek or Ollama.
