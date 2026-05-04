import argparse
from pathlib import Path

from transcript_fetcher import TranscriptNotFound, add_transcript_to_video_file


DEFAULT_VIDEOS_ROOT = Path(__file__).parent.parent / "database" / "Videos"


def iter_video_files(videos_root: Path):
    yield from videos_root.glob("*/*.json")


def add_transcripts(
    videos_root: Path = DEFAULT_VIDEOS_ROOT,
    video_json: Path | None = None,
    languages: tuple[str, ...] = ("en",),
    overwrite: bool = True,
) -> int:
    paths = [video_json] if video_json else iter_video_files(videos_root)
    count = 0
    for path in paths:
        try:
            if add_transcript_to_video_file(
                path,
                languages=languages,
                overwrite=overwrite,
            ):
                count += 1
                print(f"transcript added {path}")
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
    args = parser.parse_args()

    add_transcripts(
        videos_root=args.videos_root,
        video_json=args.video_json,
        languages=tuple(args.language),
        overwrite=not args.no_overwrite,
    )


if __name__ == "__main__":
    main()
