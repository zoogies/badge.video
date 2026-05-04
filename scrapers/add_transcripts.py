import argparse
import time
from pathlib import Path

from transcript_fetcher import TranscriptNotFound, TranscriptRateLimited, add_transcript_to_video_file


DEFAULT_VIDEOS_ROOT = Path(__file__).parent.parent / "database" / "Videos"


def iter_video_files(videos_root: Path):
    yield from videos_root.glob("*/*.json")


def add_transcripts(
    videos_root: Path = DEFAULT_VIDEOS_ROOT,
    video_json: Path | None = None,
    languages: tuple[str, ...] = ("en",),
    overwrite: bool = True,
    delay_seconds: float = 2.0,
    retries: int = 0,
    retry_backoff_seconds: float = 30.0,
) -> int:
    paths = [video_json] if video_json else iter_video_files(videos_root)
    count = 0
    for index, path in enumerate(paths):
        if index > 0 and delay_seconds > 0:
            time.sleep(delay_seconds)
        try:
            if add_transcript_to_video_file(
                path,
                languages=languages,
                overwrite=overwrite,
                retries=retries,
                retry_backoff_seconds=retry_backoff_seconds,
            ):
                count += 1
                print(f"transcript added {path}")
        except TranscriptRateLimited as exc:
            print(f"transcript rate limited {path}: {exc}")
            print("Stopping transcript batch early. Retry later or increase --delay-seconds.")
            break
        except TranscriptNotFound as exc:
            print(f"transcript missing {path}: {exc}")
        except Exception as exc:
            print(f"transcript error {path}: {exc}")
    print(f"Added transcripts to {count} video JSON files.")
    return count


def main() -> None:
    parser = argparse.ArgumentParser(description="Add YouTube transcripts inside video JSON files.")
    parser.add_argument("--videos-root", type=Path, default=DEFAULT_VIDEOS_ROOT)
    parser.add_argument("--video-json", type=Path)
    parser.add_argument("--language", action="append", default=["en"])
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--retry-backoff-seconds", type=float, default=30.0)
    args = parser.parse_args()

    add_transcripts(
        videos_root=args.videos_root,
        video_json=args.video_json,
        languages=tuple(args.language),
        overwrite=not args.no_overwrite,
        delay_seconds=args.delay_seconds,
        retries=args.retries,
        retry_backoff_seconds=args.retry_backoff_seconds,
    )


if __name__ == "__main__":
    main()
