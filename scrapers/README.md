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

Try YouTube captions through `yt-dlp`:

```powershell
uv run pipeline.py transcripts --provider ytdlp-subtitles --cookies-from-browser chrome --verbose
```

High-quality local ASR for one video:

```powershell
uv run pipeline.py transcripts --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json" --provider local-asr --asr-model large-v3 --asr-device cuda --asr-compute-type int8_float16 --cookies-from-browser chrome --verbose
```

Use local ASR as a fallback in auto mode:

```powershell
uv run pipeline.py transcripts --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json" --provider auto --allow-local-asr --verbose
```

Install local transcript tools when needed:

```powershell
uv pip install yt-dlp faster-whisper
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

Transcript providers:

- `auto`: direct YouTube caption extraction, then `yt-dlp` subtitles.
- `direct`: current timedtext/watch-page caption extraction.
- `ytdlp-subtitles`: `yt-dlp` auto/manual subtitles without downloading media.
- `local-asr`: downloads audio with `yt-dlp` and transcribes locally with `faster-whisper`.

`local-asr` defaults to `large-v3` on CUDA with `int8_float16`, which is the high-quality 8 GB GPU-oriented setting. For faster tests, use `--asr-model small.en`.

CUDA is required by default for local ASR. The project installs NVIDIA cuBLAS/cuDNN CUDA 12 wheels and adds their DLL directories at runtime, so the RTX 3070 path should be used without editing global Windows PATH.

Use CPU fallback only for a smoke test:

```powershell
uv run pipeline.py transcripts --provider local-asr --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json" --asr-fallback-device cpu --verbose
```

Disable fallback explicitly when debugging GPU setup:

```powershell
uv run pipeline.py transcripts --provider local-asr --video-json "..\database\Videos\Code Blue Cam\-BgAVL1Vh7c.json" --no-asr-fallback --verbose
```

LLM settings live in `../.env`:

```env
YOUTUBE_API_KEY=...
LLM_BACKEND=dry_run
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=...
OLLAMA_URL=http://localhost:11434/api/chat
```
