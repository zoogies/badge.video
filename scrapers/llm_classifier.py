import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from tqdm.auto import tqdm

from metadata_atlas import DEFAULT_ATLAS_PATH, rebuild_metadata_atlas


PROMPT_PATH = Path(__file__).with_name("classifier_prompt.txt")
DEFAULT_VIDEOS_ROOT = Path(__file__).parent.parent / "database" / "Videos"
DEFAULT_TRANSCRIPT_CONTEXT = "timestamped_text"
DEFAULT_CLASSIFY_WORKERS = 4
TRANSCRIPT_CONTEXT_OPTIONS = ("timestamped_text", "segments", "text", "none")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_settings() -> dict:
    load_dotenv(Path(__file__).parent.parent / ".env")
    backend = os.getenv("LLM_BACKEND", "dry_run").lower()
    default_workers = 1 if backend == "ollama" else DEFAULT_CLASSIFY_WORKERS
    return {
        "backend": backend,
        "model": os.getenv("LLM_MODEL", "deepseek-chat" if backend == "deepseek" else "llama3.1"),
        "transcript_context": os.getenv("LLM_TRANSCRIPT_CONTEXT", DEFAULT_TRANSCRIPT_CONTEXT),
        "classify_workers": _env_int("LLM_CLASSIFY_WORKERS", default_workers),
        "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY"),
        "deepseek_url": os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"),
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat"),
    }


def classify_video_file(
    video_json_path: Path,
    overwrite: bool = True,
    transcript_context: str | None = None,
    require_transcript: bool = True,
) -> bool:
    settings = load_settings()
    transcript_context = transcript_context or settings["transcript_context"]
    video = json.loads(video_json_path.read_text(encoding="utf-8"))
    if video.get("classification") and not overwrite:
        return False
    if require_transcript and not has_available_transcript(video):
        return False

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_payload = build_user_payload(video, transcript_context=transcript_context)
    result = run_backend(settings, prompt, user_payload)
    latest_video = json.loads(video_json_path.read_text(encoding="utf-8"))
    video["classification"] = {
        "generated_at": utc_now_iso(),
        "backend": settings["backend"],
        "model": settings["model"],
        "prompt_path": str(PROMPT_PATH.name),
        "transcript_context": transcript_context,
        "result": result,
    }
    latest_video["classification"] = video["classification"]
    latest_video["human_reviewed"] = False
    video_json_path.write_text(json.dumps(latest_video, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        return max(1, int(value))
    except ValueError:
        return default


def build_user_payload(video: dict, transcript_context: str = DEFAULT_TRANSCRIPT_CONTEXT) -> str:
    if transcript_context not in TRANSCRIPT_CONTEXT_OPTIONS:
        raise ValueError(f"Unsupported transcript_context: {transcript_context}")

    payload = {
        "video": {
            "video_id": video.get("video_id"),
            "title": video.get("title"),
            "url": video.get("url"),
            "published_at": video.get("published_at"),
            "video_scraped_at": video.get("video_scraped_at"),
            "channel": video.get("channel"),
            "channel_id": video.get("channel_id"),
            "description": video.get("description"),
            "duration": video.get("duration"),
            "view_count": video.get("view_count"),
            "like_count": video.get("like_count"),
            "comment_count": video.get("comment_count"),
            "tags": video.get("tags"),
        },
        "transcript": build_transcript_context(video.get("transcript"), transcript_context),
    }
    return json.dumps(payload, ensure_ascii=False)


def has_available_transcript(video: dict) -> bool:
    transcript = video.get("transcript")
    return isinstance(transcript, dict) and transcript.get("status") == "available"


def build_transcript_context(transcript: dict | None, mode: str = DEFAULT_TRANSCRIPT_CONTEXT) -> dict | None:
    if not isinstance(transcript, dict):
        return None

    context = {
        "status": transcript.get("status"),
        "source": transcript.get("source"),
        "language": transcript.get("language"),
        "scraped_at": transcript.get("scraped_at"),
        "segment_count": transcript.get("segment_count"),
        "model": transcript.get("model"),
        "details": transcript.get("details"),
    }

    if mode == "none":
        return context

    if mode == "text":
        context["text"] = transcript.get("text")
        return context

    segments = [
        segment
        for segment in transcript.get("segments") or []
        if isinstance(segment, dict) and segment.get("text")
    ]
    if mode == "timestamped_text":
        context["timestamped_text"] = "\n".join(_format_timestamped_segment(segment) for segment in segments)
        return context

    context["segments"] = [
        {
            "start": segment.get("start"),
            "end": segment.get("end"),
            "text": segment.get("text"),
        }
        for segment in segments
    ]
    return context


def _format_timestamped_segment(segment: dict) -> str:
    start = _format_seconds(segment.get("start"))
    end = _format_seconds(segment.get("end"))
    text = " ".join(str(segment.get("text", "")).split())
    if end:
        return f"[{start}-{end}] {text}"
    return f"[{start}] {text}"


def _format_seconds(value) -> str:
    if value is None:
        return "?:??"
    seconds = int(round(float(value)))
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def run_backend(settings: dict, system_prompt: str, user_payload: str) -> dict:
    backend = settings["backend"]
    if backend == "deepseek":
        content = _chat_completions(
            settings["deepseek_url"],
            settings["model"],
            system_prompt,
            user_payload,
            api_key=settings["deepseek_api_key"],
        )
    elif backend == "ollama":
        content = _ollama_chat(settings["ollama_url"], settings["model"], system_prompt, user_payload)
    elif backend == "dry_run":
        return {"needs_human_review": True, "warnings": ["LLM_BACKEND=dry_run; no classifier call was made"]}
    else:
        raise ValueError(f"Unsupported LLM_BACKEND: {backend}")

    return json.loads(content)


def _chat_completions(
    url: str,
    model: str,
    system_prompt: str,
    user_payload: str,
    api_key: str | None,
) -> str:
    if not api_key:
        raise ValueError("DEEPSEEK_API_KEY is required when LLM_BACKEND=deepseek")
    payload = {
        "model": model,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]


def _ollama_chat(url: str, model: str, system_prompt: str, user_payload: str) -> str:
    payload = {
        "model": model,
        "stream": False,
        "format": "json",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_payload},
        ],
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["message"]["content"]


def iter_video_files(videos_root: Path):
    yield from videos_root.glob("*/*.json")


def classify_videos(
    videos_root: Path = DEFAULT_VIDEOS_ROOT,
    video_json: Path | None = None,
    overwrite: bool = True,
    update_atlas: bool = True,
    atlas_path: Path = DEFAULT_ATLAS_PATH,
    transcript_context: str | None = None,
    require_transcript: bool = True,
    workers: int | None = None,
) -> int:
    settings = load_settings()
    workers = max(1, settings["classify_workers"] if workers is None else workers)
    paths = [video_json] if video_json else list(iter_video_files(videos_root))
    count = 0
    if len(paths) <= 1:
        workers = 1

    if workers == 1:
        progress = tqdm(paths, desc="Classifying", unit="video")
        for path in progress:
            progress.set_postfix(generated=count)
            try:
                if classify_video_file(
                    path,
                    overwrite=overwrite,
                    transcript_context=transcript_context,
                    require_transcript=require_transcript,
                ):
                    count += 1
                    progress.set_postfix(generated=count)
                    tqdm.write(f"classified {path}")
            except Exception as exc:
                tqdm.write(f"classification error {path}: {exc}")
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    classify_video_file,
                    path,
                    overwrite=overwrite,
                    transcript_context=transcript_context,
                    require_transcript=require_transcript,
                ): path
                for path in paths
            }
            progress = tqdm(
                as_completed(futures),
                total=len(futures),
                desc=f"Classifying ({workers} workers)",
                unit="video",
            )
            for future in progress:
                path = futures[future]
                progress.set_postfix(generated=count)
                try:
                    if future.result():
                        count += 1
                        progress.set_postfix(generated=count)
                        tqdm.write(f"classified {path}")
                except Exception as exc:
                    tqdm.write(f"classification error {path}: {exc}")
    print(f"Generated classifications for {count} video JSON files.")
    if update_atlas:
        rebuild_metadata_atlas(videos_root=videos_root, atlas_path=atlas_path)
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LLM classifications inside video JSON files.")
    parser.add_argument("--videos-root", type=Path, default=DEFAULT_VIDEOS_ROOT)
    parser.add_argument("--video-json", type=Path)
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--no-atlas", action="store_true")
    parser.add_argument("--atlas-path", type=Path, default=DEFAULT_ATLAS_PATH)
    parser.add_argument("--transcript-context", choices=TRANSCRIPT_CONTEXT_OPTIONS)
    parser.add_argument("--include-untranscribed", action="store_true")
    parser.add_argument("--classify-workers", type=int, default=None)
    args = parser.parse_args()

    classify_videos(
        videos_root=args.videos_root,
        video_json=args.video_json,
        overwrite=not args.no_overwrite,
        update_atlas=not args.no_atlas,
        atlas_path=args.atlas_path,
        transcript_context=args.transcript_context,
        require_transcript=not args.include_untranscribed,
        workers=args.classify_workers,
    )


if __name__ == "__main__":
    main()
