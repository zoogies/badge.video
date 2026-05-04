import argparse
from pathlib import Path

from add_transcripts import add_transcripts
from llm_classifier import classify_videos
from scrape_channels import CHANNELS_FILE, VIDEOS_ROOT, scrape_youtube_videos


EXAMPLES = """Examples:
  uv run pipeline.py
  uv run pipeline.py videos
  uv run pipeline.py transcripts --no-overwrite
  uv run pipeline.py transcripts --delay-seconds 10 --retries 1
  uv run pipeline.py classify --no-overwrite
  uv run pipeline.py pipeline
  uv run pipeline.py pipeline --skip-videos
  uv run pipeline.py pipeline --skip-classify
  uv run pipeline.py pipeline --video-json "..\\database\\Videos\\Code Blue Cam\\-BgAVL1Vh7c.json"

Environment:
  YOUTUBE_API_KEY=...
  LLM_BACKEND=dry_run | deepseek | ollama
  DEEPSEEK_API_KEY=...
  OLLAMA_URL=http://localhost:11434/api/chat
"""


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        print("\nNote: bare `uv run` is handled by uv itself. Use `uv run pipeline.py` for this project.")
        return

    if args.command == "videos":
        scrape_youtube_videos(channels_file=args.channels_file, videos_root=args.videos_root)
    elif args.command == "transcripts":
        add_transcripts(
            videos_root=args.videos_root,
            video_json=args.video_json,
            languages=tuple(args.language),
            overwrite=not args.no_overwrite,
            delay_seconds=args.delay_seconds,
            retries=args.retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )
    elif args.command == "classify":
        classify_videos(
            videos_root=args.videos_root,
            video_json=args.video_json,
            overwrite=not args.no_overwrite,
        )
    elif args.command == "pipeline":
        run_pipeline(args)


def run_pipeline(args: argparse.Namespace) -> None:
    if not args.skip_videos and args.video_json is None:
        scrape_youtube_videos(channels_file=args.channels_file, videos_root=args.videos_root)
    elif args.video_json is not None and not args.skip_videos:
        print("Skipping video search because --video-json targets one existing file.")

    if not args.skip_transcripts:
        add_transcripts(
            videos_root=args.videos_root,
            video_json=args.video_json,
            languages=tuple(args.language),
            overwrite=not args.no_overwrite,
            delay_seconds=args.delay_seconds,
            retries=args.retries,
            retry_backoff_seconds=args.retry_backoff_seconds,
        )

    if not args.skip_classify:
        classify_videos(
            videos_root=args.videos_root,
            video_json=args.video_json,
            overwrite=not args.no_overwrite,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run badge.video scraper stages.",
        epilog=EXAMPLES,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    videos = subparsers.add_parser("videos", help="search configured YouTube channels for new videos")
    add_channel_paths(videos)

    transcripts = subparsers.add_parser("transcripts", help="fetch transcripts into existing video JSON files")
    add_videos_root(transcripts)
    add_video_json(transcripts)
    add_transcript_options(transcripts)

    classify = subparsers.add_parser("classify", help="generate LLM classifications into video JSON files")
    add_videos_root(classify)
    add_video_json(classify)
    classify.add_argument("--no-overwrite", action="store_true")

    pipeline = subparsers.add_parser("pipeline", help="run video search, transcript fetch, and classification")
    add_channel_paths(pipeline)
    add_video_json(pipeline)
    add_transcript_options(pipeline)
    pipeline.add_argument("--skip-videos", action="store_true")
    pipeline.add_argument("--skip-transcripts", action="store_true")
    pipeline.add_argument("--skip-classify", action="store_true")

    return parser


def add_channel_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--channels-file", type=Path, default=CHANNELS_FILE)
    add_videos_root(parser)


def add_videos_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--videos-root", type=Path, default=VIDEOS_ROOT)


def add_video_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--video-json", type=Path)


def add_transcript_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--language", action="append", default=["en"])
    parser.add_argument("--no-overwrite", action="store_true")
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=0)
    parser.add_argument("--retry-backoff-seconds", type=float, default=30.0)


if __name__ == "__main__":
    main()
