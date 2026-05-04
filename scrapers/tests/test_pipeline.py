from pathlib import Path

from pipeline import build_parser


def test_default_pipeline_command_is_usage_only(capsys):
    parser = build_parser()
    parser.print_help()
    output = capsys.readouterr().out
    assert "uv run pipeline.py videos" in output
    assert "uv run pipeline.py pipeline --skip-videos" in output


def test_pipeline_parser_supports_partial_pipeline():
    args = build_parser().parse_args(["pipeline", "--skip-videos", "--skip-classify", "--no-overwrite"])
    assert args.command == "pipeline"
    assert args.skip_videos is True
    assert args.skip_classify is True
    assert args.no_overwrite is True


def test_pipeline_parser_supports_single_video_file():
    args = build_parser().parse_args(["pipeline", "--video-json", "one.json"])
    assert args.video_json == Path("one.json")


def test_pipeline_parser_supports_transcript_provider_options():
    args = build_parser().parse_args([
        "transcripts",
        "--provider",
        "local-asr",
        "--allow-local-asr",
        "--asr-model",
        "large-v3",
        "--asr-device",
        "cuda",
        "--asr-compute-type",
        "int8_float16",
        "--asr-fallback-model",
        "small.en",
        "--asr-fallback-compute-type",
        "int8",
        "--cookies-from-browser",
        "chrome",
        "--verbose",
        "--mark-unavailable",
    ])
    assert args.provider == "local-asr"
    assert args.allow_local_asr is True
    assert args.asr_model == "large-v3"
    assert args.asr_device == "cuda"
    assert args.asr_compute_type == "int8_float16"
    assert args.asr_fallback_model == "small.en"
    assert args.asr_fallback_device is None
    assert args.asr_fallback_compute_type == "int8"
    assert args.cookies_from_browser == "chrome"
    assert args.verbose is True
    assert args.mark_unavailable is True
