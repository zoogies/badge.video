import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

from dotenv import load_dotenv


PROMPT_PATH = Path(__file__).with_name("classifier_prompt.txt")
DEFAULT_VIDEOS_ROOT = Path(__file__).parent.parent / "database" / "Videos"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def load_settings() -> dict:
    load_dotenv(Path(__file__).parent.parent / ".env")
    backend = os.getenv("LLM_BACKEND", "dry_run").lower()
    return {
        "backend": backend,
        "model": os.getenv("LLM_MODEL", "deepseek-chat" if backend == "deepseek" else "llama3.1"),
        "deepseek_api_key": os.getenv("DEEPSEEK_API_KEY"),
        "deepseek_url": os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions"),
        "ollama_url": os.getenv("OLLAMA_URL", "http://localhost:11434/api/chat"),
    }


def classify_video_file(video_json_path: Path, overwrite: bool = True) -> bool:
    settings = load_settings()
    video = json.loads(video_json_path.read_text(encoding="utf-8"))
    if video.get("classification") and not overwrite:
        return False

    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    user_payload = build_user_payload(video)
    result = run_backend(settings, prompt, user_payload)
    video["classification"] = {
        "generated_at": utc_now_iso(),
        "backend": settings["backend"],
        "model": settings["model"],
        "prompt_path": str(PROMPT_PATH.name),
        "result": result,
    }
    video["human_reviewed"] = False
    video_json_path.write_text(json.dumps(video, indent=2, ensure_ascii=False), encoding="utf-8")
    return True


def build_user_payload(video: dict) -> str:
    payload = {
        "video_id": video.get("video_id"),
        "title": video.get("title"),
        "url": video.get("url"),
        "published_at": video.get("published_at"),
        "video_scraped_at": video.get("video_scraped_at"),
        "description": video.get("description"),
        "transcript": video.get("transcript"),
    }
    return json.dumps(payload, ensure_ascii=False)


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
) -> int:
    paths = [video_json] if video_json else iter_video_files(videos_root)
    count = 0
    for path in paths:
        if classify_video_file(path, overwrite=overwrite):
            count += 1
            print(f"classified {path}")
    print(f"Generated classifications for {count} video JSON files.")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate LLM classifications inside video JSON files.")
    parser.add_argument("--videos-root", type=Path, default=DEFAULT_VIDEOS_ROOT)
    parser.add_argument("--video-json", type=Path)
    parser.add_argument("--no-overwrite", action="store_true")
    args = parser.parse_args()

    classify_videos(
        videos_root=args.videos_root,
        video_json=args.video_json,
        overwrite=not args.no_overwrite,
    )


if __name__ == "__main__":
    main()
