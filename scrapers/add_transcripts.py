import argparse
import json
import time
from pathlib import Path

from tqdm.auto import tqdm

from transcript_fetcher import (
    DEFAULT_ASR_MODEL,
    DEFAULT_ASR_DEVICE,
    DEFAULT_ASR_COMPUTE_TYPE,
    DEFAULT_ASR_FALLBACK_MODEL,
    DEFAULT_ASR_FALLBACK_COMPUTE_TYPE,
    DEFAULT_ASR_FALLBACK_DEVICE,
    PROVIDERS,
    TranscriptNotFound,
    TranscriptRateLimited,
    add_transcript_to_video_file,
)


DEFAULT_VIDEOS_ROOT = Path(__file__).parent.parent / "database" / "Videos"


def iter_video_files(videos_root: Path):
    yield from videos_root.glob("*/*.json")


def add_transcripts(
    videos_root: Path = DEFAULT_VIDEOS_ROOT,
    video_json: Path | None = None,
    languages: tuple[str, ...] = ("en",),
    overwrite: bool = False,
    delay_seconds: float = 2.0,
    retries: int = 0,
    retry_backoff_seconds: float = 30.0,
    provider: str = "auto",
    allow_local_asr: bool = False,
    asr_model: str = DEFAULT_ASR_MODEL,
    asr_device: str = DEFAULT_ASR_DEVICE,
    asr_compute_type: str = DEFAULT_ASR_COMPUTE_TYPE,
    asr_fallback_model: str = DEFAULT_ASR_FALLBACK_MODEL,
    asr_fallback_device: str | None = DEFAULT_ASR_FALLBACK_DEVICE,
    asr_fallback_compute_type: str = DEFAULT_ASR_FALLBACK_COMPUTE_TYPE,
    cookies_from_browser: str | None = None,
    verbose: bool = False,
    mark_unavailable: bool = False,
    limit: int | None = None,
) -> int:
    paths = select_transcript_paths(videos_root, video_json, overwrite=overwrite, limit=limit)
    count = 0
    progress = tqdm(paths, desc="Transcripts", unit="video")
    for index, path in enumerate(progress):
        progress.set_postfix(added=count, current=path.stem)
        if index > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            if add_transcript_to_video_file(
                path,
                languages=languages,
                overwrite=overwrite,
                retries=retries,
                retry_backoff_seconds=retry_backoff_seconds,
                provider=provider,
                allow_local_asr=allow_local_asr,
                asr_model=asr_model,
                asr_device=asr_device,
                asr_compute_type=asr_compute_type,
                asr_fallback_model=asr_fallback_model,
                asr_fallback_device=asr_fallback_device,
                asr_fallback_compute_type=asr_fallback_compute_type,
                cookies_from_browser=cookies_from_browser,
                verbose=verbose,
                mark_unavailable=mark_unavailable,
            ):
                count += 1
                progress.set_postfix(added=count, current=path.stem)
                tqdm.write(f"transcript added {path}")
        except TranscriptRateLimited as exc:
            tqdm.write(f"transcript rate limited {path}: {exc}")
            tqdm.write("Stopping transcript batch early. Retry later or increase --delay-seconds.")
            break
        except TranscriptNotFound as exc:
            tqdm.write(f"transcript missing {path}: {exc}")
        except Exception as exc:
            tqdm.write(f"transcript error {path}: {exc}")
    print(f"Added transcripts to {count} video JSON files.")
    return count


def select_transcript_paths(
    videos_root: Path,
    video_json: Path | None = None,
    overwrite: bool = False,
    limit: int | None = None,
) -> list[Path]:
    if video_json:
        return [video_json]

    selected = []
    for path in iter_video_files(videos_root):
        if not overwrite and _has_existing_transcript(path):
            continue
        selected.append(path)
        if limit is not None and len(selected) >= limit:
            break
    return selected


def _has_existing_transcript(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    return bool(data.get("transcript"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Add YouTube transcripts inside video JSON files.")
    parser.add_argument("--videos-root", type=Path, default=DEFAULT_VIDEOS_ROOT)
    parser.add_argument("--video-json", type=Path)
    parser.add_argument("--language", action="append", default=["en"])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--retry-backoff-seconds", type=float, default=30.0)
    parser.add_argument("--provider", choices=PROVIDERS, default="auto")
    parser.add_argument("--allow-local-asr", action="store_true")
    parser.add_argument("--asr-model", default=DEFAULT_ASR_MODEL)
    parser.add_argument("--asr-device", default=DEFAULT_ASR_DEVICE)
    parser.add_argument("--asr-compute-type", default=DEFAULT_ASR_COMPUTE_TYPE)
    parser.add_argument("--asr-fallback-model", default=DEFAULT_ASR_FALLBACK_MODEL)
    parser.add_argument("--asr-fallback-device", default=DEFAULT_ASR_FALLBACK_DEVICE)
    parser.add_argument("--asr-fallback-compute-type", default=DEFAULT_ASR_FALLBACK_COMPUTE_TYPE)
    parser.add_argument("--no-asr-fallback", action="store_true")
    parser.add_argument("--cookies-from-browser")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--mark-unavailable", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    add_transcripts(
        videos_root=args.videos_root,
        video_json=args.video_json,
        languages=tuple(args.language),
        overwrite=args.overwrite and not args.no_overwrite,
        delay_seconds=args.delay_seconds,
        retries=args.retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
        provider=args.provider,
        allow_local_asr=args.allow_local_asr,
        asr_model=args.asr_model,
        asr_device=args.asr_device,
        asr_compute_type=args.asr_compute_type,
        asr_fallback_model=args.asr_fallback_model,
        asr_fallback_device=None if args.no_asr_fallback or not args.asr_fallback_device else args.asr_fallback_device,
        asr_fallback_compute_type=args.asr_fallback_compute_type,
        cookies_from_browser=args.cookies_from_browser,
        verbose=args.verbose,
        mark_unavailable=args.mark_unavailable,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
