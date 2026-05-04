# badge.video scrapers

Minimal usage:

```powershell
uv run pipeline.py
```

Discover new YouTube videos from `../database/channels.json`:

```powershell
uv run pipeline.py videos
```

Fetch transcripts for all videos:

```powershell
uv run pipeline.py transcripts --no-overwrite
```

Use a slower transcript run if YouTube starts returning 429s:

```powershell
uv run pipeline.py transcripts --delay-seconds 10 --retries 1 --retry-backoff-seconds 120
```

Classify all videos with the configured LLM backend:

```powershell
uv run pipeline.py classify --no-overwrite
```

Run the whole pipeline:

```powershell
uv run pipeline.py pipeline
```

Single-video local testing:

```powershell
uv run pipeline.py transcripts --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json"
uv run pipeline.py classify --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json"
uv run pipeline.py pipeline --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json" --skip-videos
```

Review behavior:

- New video JSON files start with `"human_reviewed": false`.
- Re-scraping preserves existing fields, including transcript, classification, and manual fields.
- Re-scraping clears `human_reviewed` only when core YouTube metadata changes.
- Re-running classification clears `human_reviewed`.

LLM settings live in `../.env`:

```env
YOUTUBE_API_KEY=...
LLM_BACKEND=dry_run
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=...
OLLAMA_URL=http://localhost:11434/api/chat
```
