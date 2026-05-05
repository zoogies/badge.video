import argparse
from pathlib import Path

from add_transcripts import add_transcripts
from build_frontend_data import DEFAULT_FRONTEND_DATA_DIR, build_frontend_data
from llm_classifier import TRANSCRIPT_CONTEXT_OPTIONS, classify_videos
from metadata_atlas import DEFAULT_ATLAS_PATH, rebuild_metadata_atlas
from scrape_channels import CHANNELS_FILE, VIDEOS_ROOT, scrape_youtube_videos
from transcript_fetcher import (
    DEFAULT_ASR_COMPUTE_TYPE,
    DEFAULT_ASR_DEVICE,
    DEFAULT_ASR_FALLBACK_MODEL,
    DEFAULT_ASR_FALLBACK_COMPUTE_TYPE,
    DEFAULT_ASR_FALLBACK_DEVICE,
    DEFAULT_ASR_MODEL,
    PROVIDERS,
)


EXAMPLES = """Examples:
  uv run pipeline.py
  uv run pipeline.py videos
  uv run pipeline.py transcripts
  uv run pipeline.py transcripts --overwrite
  uv run pipeline.py transcripts --provider ytdlp-subtitles --cookies-from-browser chrome
  uv run pipeline.py transcripts --video-json "..\\database\\Videos\\Code Blue Cam\\-BgAVL1Vh7c.json" --provider local-asr --verbose
  uv run pipeline.py transcripts --delay-seconds 10 --retries 1
  uv run pipeline.py classify --no-overwrite
  uv run pipeline.py classify --transcript-context timestamped_text
  uv run pipeline.py atlas
  uv run pipeline.py site-data
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
    elif args.command == "classify":
        classify_videos(
            videos_root=args.videos_root,
            video_json=args.video_json,
            overwrite=not args.no_overwrite,
            update_atlas=not args.no_atlas,
            atlas_path=args.atlas_path,
            transcript_context=args.transcript_context,
            require_transcript=not args.include_untranscribed,
        )
    elif args.command == "atlas":
        rebuild_metadata_atlas(videos_root=args.videos_root, atlas_path=args.atlas_path)
    elif args.command == "site-data":
        build_frontend_data(
            videos_root=args.videos_root,
            atlas_path=args.atlas_path,
            output_dir=args.output_dir,
            repo_slug=args.repo,
            rebuild_atlas=not args.no_atlas,
            include_unclassified=args.include_unclassified,
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

    if not args.skip_classify:
        classify_videos(
            videos_root=args.videos_root,
            video_json=args.video_json,
            overwrite=not args.no_overwrite,
            update_atlas=not args.no_atlas,
            atlas_path=args.atlas_path,
            transcript_context=args.transcript_context,
            require_transcript=not args.include_untranscribed,
        )
    elif not args.no_atlas:
        rebuild_metadata_atlas(videos_root=args.videos_root, atlas_path=args.atlas_path)


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
    add_classify_options(classify)
    add_atlas_options(classify, include_toggle=True)

    atlas = subparsers.add_parser("atlas", help="rebuild global frontend metadata filters")
    add_videos_root(atlas)
    add_atlas_options(atlas)

    site_data = subparsers.add_parser("site-data", help="build compact static JSON for the frontend")
    add_videos_root(site_data)
    add_atlas_options(site_data, include_toggle=True)
    site_data.add_argument("--output-dir", type=Path, default=DEFAULT_FRONTEND_DATA_DIR)
    site_data.add_argument("--repo", default="zoogies/badge.video")
    site_data.add_argument("--include-unclassified", action="store_true")

    pipeline = subparsers.add_parser("pipeline", help="run video search, transcript fetch, and classification")
    add_channel_paths(pipeline)
    add_video_json(pipeline)
    add_transcript_options(pipeline)
    pipeline.add_argument("--skip-videos", action="store_true")
    pipeline.add_argument("--skip-transcripts", action="store_true")
    pipeline.add_argument("--skip-classify", action="store_true")
    add_classify_options(pipeline)
    add_atlas_options(pipeline, include_toggle=True)

    return parser


def add_channel_paths(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--channels-file", type=Path, default=CHANNELS_FILE)
    add_videos_root(parser)


def add_videos_root(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--videos-root", type=Path, default=VIDEOS_ROOT)


def add_video_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--video-json", type=Path)


def add_atlas_options(parser: argparse.ArgumentParser, include_toggle: bool = False) -> None:
    parser.add_argument("--atlas-path", type=Path, default=DEFAULT_ATLAS_PATH)
    if include_toggle:
        parser.add_argument("--no-atlas", action="store_true")


def add_transcript_options(parser: argparse.ArgumentParser) -> None:
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


def add_classify_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--transcript-context",
        choices=TRANSCRIPT_CONTEXT_OPTIONS,
        help="Override LLM_TRANSCRIPT_CONTEXT for this run: timestamped_text keeps timestamps compactly, text is smaller, none sends only transcript metadata.",
    )
    parser.add_argument(
        "--include-untranscribed",
        action="store_true",
        help="Classify videos even when no transcript is available.",
    )


if __name__ == "__main__":
    main()
